#import <Foundation/Foundation.h>

/* Scope macOS scheduling hints to a running media session. They neither
 * change global sleep preferences nor require elevated privileges. */
void *fitlab_media_begin(void) {
    @autoreleasepool {
        id token = [[NSProcessInfo processInfo]
            beginActivityWithOptions:(NSActivityUserInitiated | NSActivityIdleDisplaySleepDisabled | NSActivityLatencyCritical)
            reason:@"FIT-LAB live radio video"];
        return [token retain];
    }
}

void fitlab_media_end(void *token) {
    if (!token) return;
    @autoreleasepool {
        [[NSProcessInfo processInfo] endActivity:(id)token];
        [(id)token release];
    }
}
