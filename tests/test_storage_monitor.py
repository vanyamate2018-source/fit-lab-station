from master.storage_monitor import mount_candidates


def test_usb_filesystem_and_sd_are_found_but_not_internal_or_mounted():
    devices=[{'path':'/dev/sda','type':'disk','tran':'usb','children':[
        {'path':'/dev/sda1','type':'part','fstype':'vfat','mountpoints':[None]},
        {'path':'/dev/sda2','type':'part','fstype':'ext4','mountpoints':['/media/data']}]},
        {'path':'/dev/mmcblk1','type':'disk','rm':True,'fstype':'exfat'},
        {'path':'/dev/nvme0n1p1','type':'part','fstype':'ext4'}]
    assert mount_candidates(devices)==['/dev/sda1','/dev/mmcblk1']


def test_system_usb_disk_and_encrypted_partitions_are_not_mounted():
    assert mount_candidates([{'path':'/dev/sda','type':'disk','tran':'usb','children':[
        {'path':'/dev/sda1','type':'part','fstype':'ext4','mountpoints':['/']},
        {'path':'/dev/sda2','type':'part','fstype':'vfat'}]}])==[]
    assert mount_candidates([{'path':'/dev/sdb1','type':'part','rm':True,'fstype':'crypto_LUKS'}])==[]
