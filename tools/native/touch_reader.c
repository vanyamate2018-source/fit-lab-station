// Read only the MPI7009 digitizer. No event injection or exclusive USB claim.
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/hid/IOHIDManager.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>

static volatile sig_atomic_t running = 1;
static unsigned devices = 0;
static void stop(int sig) { running = 0; }
static void report(void *ctx, IOReturn result, void *sender, IOHIDReportType type,
                   uint32_t reportID, uint8_t *data, CFIndex length) {
    if (result || reportID != 1 || length != 56 || data[0] != 1) return;
    printf("{\"type\":\"report\",\"data\":\"");
    for (CFIndex i = 0; i < length; i++) printf("%02x", data[i]);
    puts("\"}");
}
static void added(void *ctx, IOReturn result, void *sender, IOHIDDeviceRef device) {
    if (result) return;
    devices++;
    printf("{\"type\":\"connected\",\"devices\":%u}\n", devices);
}
static void removed(void *ctx, IOReturn result, void *sender, IOHIDDeviceRef device) {
    if (devices) devices--;
    printf("{\"type\":\"removed\",\"devices\":%u}\n", devices);
}
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGTERM, stop); signal(SIGINT, stop);
    IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, 0);
    int values[] = {1810, 9, 13, 4};
    CFStringRef keys[] = {CFSTR(kIOHIDVendorIDKey), CFSTR(kIOHIDProductIDKey),
                         CFSTR(kIOHIDPrimaryUsagePageKey), CFSTR(kIOHIDPrimaryUsageKey)};
    CFMutableDictionaryRef match = CFDictionaryCreateMutable(NULL, 4, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    for (int i=0;i<4;i++) {
        CFNumberRef v = CFNumberCreate(NULL, kCFNumberIntType, &values[i]);
        CFDictionarySetValue(match, keys[i], v); CFRelease(v);
    }
    IOHIDManagerSetDeviceMatching(manager, match); CFRelease(match);
    IOHIDManagerRegisterDeviceMatchingCallback(manager, added, NULL);
    IOHIDManagerRegisterDeviceRemovalCallback(manager, removed, NULL);
    IOHIDManagerRegisterInputReportCallback(manager, report, NULL);
    IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    IOReturn rc = IOHIDManagerOpen(manager, kIOHIDOptionsTypeNone);
    printf("{\"type\":\"open\",\"result\":%d}\n", rc);
    if (rc) { CFRelease(manager); return 2; }
    pid_t parent = getppid();
    double start = CFAbsoluteTimeGetCurrent();
    int seconds = argc > 1 ? atoi(argv[1]) : 0;
    while (running && getppid() == parent && (!seconds || CFAbsoluteTimeGetCurrent()-start < seconds))
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, false);
    IOHIDManagerUnscheduleFromRunLoop(manager, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    IOHIDManagerClose(manager, 0); CFRelease(manager);
    return 0;
}
