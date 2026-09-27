#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <stdint.h>
#include <stddef.h>

typedef struct { uint32_t address, location; } FitLabUSBDevice;

static uint32_t number(io_service_t service, CFStringRef name) {
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, name, kCFAllocatorDefault, 0);
    int64_t result = 0;
    if (value) {
        if (CFGetTypeID(value) == CFNumberGetTypeID())
            CFNumberGetValue((CFNumberRef)value, kCFNumberSInt64Type, &result);
        CFRelease(value);
    }
    return result >= 0 && result <= UINT32_MAX ? (uint32_t)result : 0;
}

/* Read registry properties only. Never seize, configure or open a USB device. */
int fitlab_usb_inventory(uint32_t vendor, uint32_t product,
                         FitLabUSBDevice *devices, size_t capacity) {
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBHostDevice"),
                                    &iterator) != KERN_SUCCESS) return -1;
    int count = 0;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        if (number(service, CFSTR("idVendor")) == vendor &&
            number(service, CFSTR("idProduct")) == product &&
            number(service, CFSTR("bNumConfigurations"))) {
            if ((size_t)count < capacity) {
                uint32_t address = number(service, CFSTR("USB Address"));
                if (!address) address = number(service, CFSTR("kUSBAddress"));
                devices[count] = (FitLabUSBDevice){address, number(service, CFSTR("locationID"))};
            }
            count++;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return count;
}
