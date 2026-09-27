// MPI7009 input bridge. Only real reports from 0712:0009 can produce events.
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <IOKit/hid/IOHIDManager.h>
#import <ServiceManagement/ServiceManagement.h>
#include <memory>
#include <set>
#include <sys/file.h>
#include <fcntl.h>
#include "touch_gestures.hpp"

static NSString *const StatePath=@"/Volumes/FIT-LAB/data/logs/system-touch-status.json";
static bool connected=false, trusted=false, enabled=false, paused=false, mouseDown=false;
static CGRect bounds=CGRectZero;
static CGDirectDisplayID display=0;
static unsigned reports=0, maxContacts=0, clicks=0, scrolls=0;
static double lastInput=0, activateAfter=0, scrollRemainder=0;
static std::unique_ptr<fitlab::Gestures> gestures;
static IOHIDManagerRef hid=nullptr;
static CGEventSourceRef source=nullptr;
static CFTimeInterval lastClick=0, lastStatusWrite=0;
static bool loginAttempted=false;
static dispatch_source_t termination;
static CGPoint lastClickPoint=CGPointZero;
static int clickCount=1;

static void output(fitlab::Action action) {
    if(!trusted) return;
    CGEventRef event=nullptr;
    if(action.kind==fitlab::Scroll) {
        scrollRemainder+=action.delta;
        int pixels=round(scrollRemainder); scrollRemainder-=pixels;
        if(!pixels) return;
        event=CGEventCreateScrollWheelEvent(source,kCGScrollEventUnitPixel,1,pixels);
        scrolls++;
    } else {
        CGEventType kind=kCGEventMouseMoved;
        if(action.kind==fitlab::Down) {
            double now=CFAbsoluteTimeGetCurrent();
            clickCount=(now-lastClick<[NSEvent doubleClickInterval] &&
                hypot(action.x-lastClickPoint.x,action.y-lastClickPoint.y)<12) ? clickCount+1 : 1;
            lastClick=now; lastClickPoint=CGPointMake(action.x,action.y);
            mouseDown=true; kind=kCGEventLeftMouseDown; clicks++;
        } else if(action.kind==fitlab::Up) { mouseDown=false; kind=kCGEventLeftMouseUp; }
        else if(mouseDown) kind=kCGEventLeftMouseDragged;
        event=CGEventCreateMouseEvent(source,kind,CGPointMake(action.x,action.y),kCGMouseButtonLeft);
        CGEventSetIntegerValueField(event,kCGMouseEventClickState,clickCount);
    }
    CGEventPost(kCGHIDEventTap,event); CFRelease(event);
}
static void locateDisplay() {
    CGDirectDisplayID ids[32]; uint32_t count=0;
    CGGetOnlineDisplayList(32,ids,&count);
    CGDirectDisplayID found=0;
    for(uint32_t i=0;i<count;i++)
        if(CGDisplayVendorNumber(ids[i])==0x3609 && CGDisplayModelNumber(ids[i])==0x7009) { found=ids[i]; break; }
    CGRect next=found ? CGDisplayBounds(found) : CGRectZero;
    if(found!=display || !CGRectEqualToRect(bounds,next)) {
        gestures->cancel(); display=found; bounds=next;
    }
}
static void statusFile() {
    NSDictionary *state=@{@"pid":@(getpid()),@"timestamp":@([[NSDate date] timeIntervalSince1970]),
      @"connected":@(connected),@"trusted":@(trusted),@"enabled":@(enabled),@"paused":@(paused),
      @"display":@(display),@"width":@(bounds.size.width),@"height":@(bounds.size.height),
      @"reports":@(reports),@"max_contacts":@(maxContacts),@"clicks":@(clicks),@"scrolls":@(scrolls),
      @"login_status":@([SMAppService mainAppService].status)};
    NSData *data=[NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:StatePath options:NSDataWritingAtomic error:nil];
}
static void input(void*, IOReturn result, void*, IOHIDReportType, uint32_t reportID, uint8_t *data, CFIndex length) {
    if(result || reportID!=1 || length!=56 || data[0]!=1 || data[55]>10) return;
    reports++; lastInput=CFAbsoluteTimeGetCurrent();
    std::vector<fitlab::Point> contacts;
    std::set<int> ids;
    for(int slot=0;slot<data[55];slot++) {
        int offset=1+slot*5;
        if(!(data[offset]&0x40)) continue;
        int id=data[offset]&63, x=data[offset+1]|data[offset+2]<<8, y=data[offset+3]|data[offset+4]<<8;
        if(x>1024 || y>600 || !ids.insert(id).second) { gestures->cancel(); return; }
        contacts.push_back({id,bounds.origin.x+x/1024.0*(bounds.size.width-1),
                              bounds.origin.y+y/600.0*(bounds.size.height-1)});
    }
    maxContacts=std::max(maxContacts,(unsigned)contacts.size());
    if(enabled && CFAbsoluteTimeGetCurrent()>activateAfter) gestures->update(contacts,lastInput);
    else gestures->cancel();
}
static void added(void*, IOReturn result, void*, IOHIDDeviceRef) { if(!result) connected=true; }
static void removed(void*, IOReturn, void*, IOHIDDeviceRef) { connected=false; gestures->cancel(); }

@interface TouchDelegate : NSObject<NSApplicationDelegate>
@property(strong) NSStatusItem *item;
@property(strong) NSMenuItem *stateItem;
@property(strong) NSMenuItem *pauseItem;
@property(strong) NSMenuItem *loginItem;
@property(strong) NSTimer *timer;
@end
@implementation TouchDelegate
- (void)permissions:(id)sender {
    NSDictionary *options=@{(__bridge NSString*)kAXTrustedCheckOptionPrompt:@YES};
    AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]];
}
- (void)togglePause:(id)sender { paused=!paused; gestures->cancel(); [self tick:nil]; }
- (void)toggleLogin:(id)sender {
    NSError *error=nil;
    SMAppService *service=[SMAppService mainAppService];
    if(service.status==SMAppServiceStatusEnabled) [service unregisterAndReturnError:&error];
    else [service registerAndReturnError:&error];
    if(error) { NSAlert *alert=[NSAlert new]; alert.messageText=@"Автозапуск"; alert.informativeText=error.localizedDescription; [alert runModal]; }
    NSDictionary *preference=@{@"autostart":@(service.status==SMAppServiceStatusEnabled)};
    [[NSJSONSerialization dataWithJSONObject:preference options:0 error:nil] writeToFile:@"/Volumes/FIT-LAB/data/config/touch-service.json" atomically:YES];
    [self tick:nil];
}
- (void)quit:(id)sender { [NSApp terminate:nil]; }
- (void)tick:(id)sender {
    locateDisplay();
    bool was=enabled;
    trusted=AXIsProcessTrusted();
    enabled=trusted && connected && display && !paused;
    if(enabled && !was) activateAfter=CFAbsoluteTimeGetCurrent()+2;
    if(!enabled || CFAbsoluteTimeGetCurrent()-lastInput>3) gestures->cancel();
    else gestures->hold(CFAbsoluteTimeGetCurrent());
    self.stateItem.title=!trusted ? @"Нужно разрешение macOS" : !display ? @"Ожидание MPI7009" : !connected ? @"Ожидание USB сенсора" : paused ? @"На паузе" : @"MPI7009 · работает";
    self.item.button.title=enabled ? @"◉" : @"◎";
    self.pauseItem.title=paused ? @"Включить сенсор" : @"Приостановить сенсор";
    self.loginItem.state=[SMAppService mainAppService].status==SMAppServiceStatusEnabled ? NSControlStateValueOn : NSControlStateValueOff;
    if(trusted && !loginAttempted) {
        loginAttempted=true;
        NSData *saved=[NSData dataWithContentsOfFile:@"/Volumes/FIT-LAB/data/config/touch-service.json"];
        NSDictionary *preference=saved ? [NSJSONSerialization JSONObjectWithData:saved options:0 error:nil] : nil;
        if((!preference || [preference[@"autostart"] boolValue]) && ([SMAppService mainAppService].status==SMAppServiceStatusNotRegistered || [SMAppService mainAppService].status==SMAppServiceStatusNotFound)) {
            NSError *error=nil;
            [[SMAppService mainAppService] registerAndReturnError:&error];
            if(error) NSLog(@"Login registration: %@",error.localizedDescription);
        }
    }
    if(was!=enabled || CFAbsoluteTimeGetCurrent()-lastStatusWrite>.5) {
        statusFile(); lastStatusWrite=CFAbsoluteTimeGetCurrent();
    }
}
- (void)applicationDidFinishLaunching:(NSNotification*)note {
    self.item=[[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
    self.item.button.toolTip=@"FIT-LAB Touch";
    NSMenu *menu=[NSMenu new];
    self.stateItem=[menu addItemWithTitle:@"Проверка сенсора" action:nil keyEquivalent:@""];
    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *permission=[menu addItemWithTitle:@"Разрешить управление…" action:@selector(permissions:) keyEquivalent:@""]; permission.target=self;
    self.pauseItem=[menu addItemWithTitle:@"Приостановить сенсор" action:@selector(togglePause:) keyEquivalent:@""]; self.pauseItem.target=self;
    self.loginItem=[menu addItemWithTitle:@"Запускать при входе" action:@selector(toggleLogin:) keyEquivalent:@""]; self.loginItem.target=self;
    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *quit=[menu addItemWithTitle:@"Завершить FIT-LAB Touch" action:@selector(quit:) keyEquivalent:@""]; quit.target=self;
    self.item.menu=menu;
    source=CGEventSourceCreate(kCGEventSourceStatePrivate);
    gestures=std::make_unique<fitlab::Gestures>(output);
    hid=IOHIDManagerCreate(kCFAllocatorDefault,0);
    NSDictionary *match=@{@kIOHIDVendorIDKey:@1810,@kIOHIDProductIDKey:@9,@kIOHIDPrimaryUsagePageKey:@13,@kIOHIDPrimaryUsageKey:@4};
    IOHIDManagerSetDeviceMatching(hid,(__bridge CFDictionaryRef)match);
    IOHIDManagerRegisterDeviceMatchingCallback(hid,added,nullptr);
    IOHIDManagerRegisterDeviceRemovalCallback(hid,removed,nullptr);
    IOHIDManagerRegisterInputReportCallback(hid,input,nullptr);
    IOHIDManagerScheduleWithRunLoop(hid,CFRunLoopGetMain(),kCFRunLoopCommonModes);
    IOHIDManagerOpen(hid,kIOHIDOptionsTypeNone);
    self.timer=[NSTimer scheduledTimerWithTimeInterval:.1 target:self selector:@selector(tick:) userInfo:nil repeats:YES];
    [[NSRunLoop mainRunLoop] addTimer:self.timer forMode:NSRunLoopCommonModes];
    signal(SIGTERM,SIG_IGN);
    termination=dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL,SIGTERM,0,dispatch_get_main_queue());
    dispatch_source_set_event_handler(termination,^{ [NSApp terminate:nil]; });
    dispatch_resume(termination);
    [self tick:nil];
    if(!trusted) {
        NSDictionary *options=@{(__bridge NSString*)kAXTrustedCheckOptionPrompt:@YES};
        AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
    }
}
- (void)applicationWillTerminate:(NSNotification*)note {
    gestures->cancel(); enabled=false; statusFile();
    IOHIDManagerClose(hid,0); CFRelease(hid); CFRelease(source);
}
@end
int main(int argc,char **argv) {
    // One instance can own pointer state; extra launches exit without events.
    int lock=open("/Volumes/FIT-LAB/data/logs/.touch-service.lock",O_CREAT|O_RDWR,0600);
    if(lock<0 || flock(lock,LOCK_EX|LOCK_NB)) return 0;
    @autoreleasepool {
        NSApplication *app=[NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        TouchDelegate *delegate=[TouchDelegate new]; app.delegate=delegate;
        [app run];
    }
    return 0;
}
