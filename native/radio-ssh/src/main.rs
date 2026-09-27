//! A bounded localhost SSH relay over WFB's length-prefixed IPv4 records.
//! No TUN device, root privileges, arbitrary destinations or payload logging.
use anyhow::{bail, Context, Result};
use clap::Parser;
use smoltcp::iface::{Config, Interface, SocketHandle, SocketSet};
use smoltcp::phy::{Device, DeviceCapabilities, Medium, RxToken, TxToken};
use smoltcp::socket::tcp;
use smoltcp::time::{Duration, Instant};
use smoltcp::wire::{HardwareAddress, IpAddress, IpCidr};
use std::collections::VecDeque;
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream, UdpSocket};

#[derive(Parser)]
struct Args {
    #[arg(long, default_value_t = 19022)]
    listen_port: u16,
    #[arg(long, default_value_t = 56551)]
    receive_port: u16,
    #[arg(long, default_value_t = 56550)]
    transmit_port: u16,
}

struct RadioDevice { udp: UdpSocket, incoming: VecDeque<Vec<u8>> }
struct Rx(Vec<u8>);
struct Tx<'a>(&'a UdpSocket);
impl RxToken for Rx {
    fn consume<R, F>(self, f: F) -> R where F: FnOnce(&[u8]) -> R { f(&self.0) }
}
impl TxToken for Tx<'_> {
    fn consume<R, F>(self, len: usize, f: F) -> R where F: FnOnce(&mut [u8]) -> R {
        let mut record = vec![0; len + 2];
        record[..2].copy_from_slice(&(len as u16).to_be_bytes());
        let result = f(&mut record[2..]);
        // UDP loss is handled by TCP retransmission, never by an unbounded queue.
        let _ = self.0.send(&record);
        result
    }
}
impl Device for RadioDevice {
    type RxToken<'a> = Rx;
    type TxToken<'a> = Tx<'a>;
    fn receive(&mut self, _: Instant) -> Option<(Rx, Tx<'_>)> {
        self.incoming.pop_front().map(|p| (Rx(p), Tx(&self.udp)))
    }
    fn transmit(&mut self, _: Instant) -> Option<Tx<'_>> { Some(Tx(&self.udp)) }
    fn capabilities(&self) -> DeviceCapabilities {
        let mut caps = DeviceCapabilities::default();
        caps.medium = Medium::Ip;
        caps.max_transmission_unit = 1024;
        caps.max_burst_size = Some(4);
        caps
    }
}

fn camera_tcp(packet: &[u8]) -> bool {
    if packet.len() < 40 || packet[0] >> 4 != 4 { return false; }
    let hlen = (packet[0] & 15) as usize * 4;
    hlen >= 20 && packet.len() >= hlen + 20
        && u16::from_be_bytes([packet[2], packet[3]]) as usize == packet.len()
        && (u16::from_be_bytes([packet[6], packet[7]]) & 0x3fff) == 0
        && packet[9] == 6 && packet[12..16] == [10, 5, 0, 10]
        && packet[16..20] == [10, 5, 0, 1]
        && packet[hlen..hlen+2] == 22u16.to_be_bytes()
}

fn records(mut data: &[u8], queue: &mut VecDeque<Vec<u8>>) {
    while data.len() >= 2 && queue.len() < 64 {
        let len = u16::from_be_bytes([data[0], data[1]]) as usize;
        data = &data[2..];
        if len > data.len() || len == 0 { return; }
        if camera_tcp(&data[..len]) { queue.push_back(data[..len].to_vec()); }
        data = &data[len..];
    }
}

struct Client { stream: TcpStream, handle: SocketHandle, eof: bool }
fn main() -> Result<()> {
    let args = Args::parse();
    if [args.listen_port, args.receive_port, args.transmit_port].contains(&0) { bail!("ports must be nonzero"); }
    let listener = TcpListener::bind(("127.0.0.1", args.listen_port))?;
    listener.set_nonblocking(true)?;
    let udp = UdpSocket::bind(("127.0.0.1", args.receive_port))?;
    udp.connect(("127.0.0.1", args.transmit_port))?;
    udp.set_nonblocking(true)?;
    let mut device = RadioDevice { udp, incoming: VecDeque::new() };
    let mut seed = [0; 8];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut seed)?;
    let mut config = Config::new(HardwareAddress::Ip);
    config.random_seed = u64::from_ne_bytes(seed);
    let started = std::time::Instant::now();
    let mut iface = Interface::new(config, &mut device, Instant::from_millis(0));
    iface.update_ip_addrs(|a| { a.push(IpCidr::new(IpAddress::v4(10, 5, 0, 1), 24)).unwrap(); });
    let mut sockets = SocketSet::new(vec![]);
    let mut clients: Vec<Client> = Vec::new();
    let mut next_port = 40000u16;
    let parent = unsafe { libc::getppid() };
    println!("{{\"state\":\"ready\",\"listen_port\":{}}}", args.listen_port);
    let mut datagram = [0; 65535];
    loop {
        if unsafe { libc::getppid() } != parent { return Ok(()); }
        let now = Instant::from_millis(started.elapsed().as_millis() as i64);
        for _ in 0..32 {
            match device.udp.recv(&mut datagram) {
                Ok(n) => records(&datagram[..n], &mut device.incoming),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(e) if e.kind() == io::ErrorKind::ConnectionRefused => break,
                Err(e) => return Err(e).context("radio transport"),
            }
        }
        if let Ok((stream, _)) = listener.accept() {
            if clients.len() < 4 {
                stream.set_nonblocking(true)?;
                stream.set_nodelay(true)?;
                let mut tcp = tcp::Socket::new(tcp::SocketBuffer::new(vec![0; 32768]), tcp::SocketBuffer::new(vec![0; 32768]));
                tcp.set_nagle_enabled(false);
                tcp.set_ack_delay(None);
                tcp.set_timeout(Some(Duration::from_secs(20)));
                next_port = if next_port >= 60000 { 40000 } else { next_port + 1 };
                tcp.connect(iface.context(), (IpAddress::v4(10, 5, 0, 10), 22), next_port).map_err(|e| anyhow::anyhow!("TCP connect: {e:?}"))?;
                clients.push(Client { stream, handle: sockets.add(tcp), eof: false });
            }
        }
        iface.poll(now, &mut device, &mut sockets);
        for client in &mut clients {
            let tcp = sockets.get_mut::<tcp::Socket>(client.handle);
            if tcp.can_recv() {
                let mut failed = false;
                let _ = tcp.recv(|bytes| match client.stream.write(bytes) {
                    Ok(n) => (n, ()),
                    Err(e) if e.kind() == io::ErrorKind::WouldBlock => (0, ()),
                    Err(_) => { failed = true; (0, ()) },
                });
                if failed { tcp.abort(); }
            }
            if tcp.can_send() && !client.eof {
                let count = (tcp.send_capacity() - tcp.send_queue()).min(4096);
                let mut bytes = [0; 4096];
                if count > 0 { match client.stream.read(&mut bytes[..count]) {
                    Ok(0) => { client.eof = true; tcp.close(); },
                    Ok(n) => { tcp.send_slice(&bytes[..n]).map_err(|e| anyhow::anyhow!("TCP queue: {e:?}"))?; },
                    Err(e) if e.kind() == io::ErrorKind::WouldBlock => {},
                    Err(_) => tcp.abort(),
                } }
            }
            if tcp.state() == tcp::State::CloseWait && !tcp.can_recv() { tcp.close(); }
        }
        clients.retain(|client| {
            if sockets.get::<tcp::Socket>(client.handle).state() == tcp::State::Closed {
                sockets.remove(client.handle); false
            } else { true }
        });
        iface.poll(now, &mut device, &mut sockets);
        std::thread::sleep(std::time::Duration::from_millis(2));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_only_complete_unfragmented_camera_ssh() {
        let mut p = vec![0; 40]; p[0]=0x45; p[3]=40; p[9]=6;
        p[12..16].copy_from_slice(&[10,5,0,10]); p[16..20].copy_from_slice(&[10,5,0,1]); p[21]=22;
        assert!(camera_tcp(&p));
        p[6]=0x20; assert!(!camera_tcp(&p)); p[6]=0;
        p[21]=80; assert!(!camera_tcp(&p)); p[21]=22;
        let mut q = VecDeque::new(); let mut record=vec![0,41]; record.extend(&p);
        records(&record,&mut q); assert!(q.is_empty());
        record[1]=40; records(&record,&mut q); assert_eq!(q.len(),1);
    }
}
