#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <LocalAuthentication/LocalAuthentication.h>
#include <string.h>

static NSDictionary *query(const char *account) {
    LAContext *context = [LAContext new];
    context.interactionNotAllowed = YES;
    return @{(__bridge id)kSecClass: (__bridge id)kSecClassGenericPassword,
             (__bridge id)kSecAttrService: @"lab.fit.station.camera-login",
             (__bridge id)kSecAttrAccount: [NSString stringWithUTF8String:account],
             (__bridge id)kSecUseAuthenticationUI: (__bridge id)kSecUseAuthenticationUIFail,
             (__bridge id)kSecUseAuthenticationContext: context};
}

// Return byte count, zero when missing, or an OSStatus. Never invoke a modal
// keychain prompt from a worker; a locked/unavailable vault falls back to login.
long fitlab_credential_read(const char *account, void *buffer, size_t capacity) {
    @autoreleasepool {
        SecKeychainSetUserInteractionAllowed(false);
        NSMutableDictionary *q = [query(account) mutableCopy];
        q[(__bridge id)kSecReturnData] = @YES;
        CFTypeRef found = NULL;
        OSStatus status = SecItemCopyMatching((__bridge CFDictionaryRef)q, &found);
        if (status == errSecItemNotFound) return 0;
        if (status != errSecSuccess) return status;
        if (!found || CFGetTypeID(found) != CFDataGetTypeID()) {
            if (found) CFRelease(found);
            return errSecDecode;
        }
        CFIndex length = CFDataGetLength((CFDataRef)found);
        if (length < 0 || (size_t)length > capacity) {
            CFRelease(found);
            return errSecBufferTooSmall;
        }
        memcpy(buffer, CFDataGetBytePtr((CFDataRef)found), (size_t)length);
        CFRelease(found);
        return length;
    }
}

int fitlab_credential_write(const char *account, const void *buffer, size_t length) {
    @autoreleasepool {
        SecKeychainSetUserInteractionAllowed(false);
        if (length > 8192) return errSecParam;
        NSData *secret = [NSData dataWithBytes:buffer length:length];
        NSDictionary *attributes = @{(__bridge id)kSecValueData: secret};
        OSStatus status = SecItemUpdate((__bridge CFDictionaryRef)query(account),
                                       (__bridge CFDictionaryRef)attributes);
        if (status == errSecItemNotFound) {
            NSMutableDictionary *q = [query(account) mutableCopy];
            q[(__bridge id)kSecValueData] = secret;
            q[(__bridge id)kSecAttrLabel] = @"FIT-LAB · вход в камеру";
            status = SecItemAdd((__bridge CFDictionaryRef)q, NULL);
        }
        return status;
    }
}
