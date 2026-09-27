#import <Foundation/Foundation.h>
#include <Python.h>
#include <unistd.h>

/* The UI process belongs to the FIT-LAB bundle. Python is embedded rather
 * than exec'ed, so macOS uses our name, icon and application identity. */
int main(int argc, char **argv) {
    @autoreleasepool {
        [[NSProcessInfo processInfo] setProcessName:@"FIT-LAB Station"];
        setenv("FIT_LAB_ROOT", "/Volumes/FIT-LAB", 1);
        setenv("FIT_LAB_DATA_ROOT", "/Volumes/FIT-LAB/data", 1);
        setenv("PYTHONPYCACHEPREFIX", "/Volumes/FIT-LAB/data/cache/python", 1);
        setenv("TMPDIR", "/Volumes/FIT-LAB/data/temp", 1);
        setenv("XDG_CACHE_HOME", "/Volumes/FIT-LAB/data/cache", 1);
        const char *flags[] = {"FIT_LAB_TEST_LOSS", "FIT_LAB_VERIFY_CRYPTO", "FIT_LAB_VIEW_SECONDS", "FIT_LAB_AUTOSTART_RADIO", NULL};
        for (int i = 0; flags[i]; i++) unsetenv(flags[i]);
        if (chdir("/Volumes/FIT-LAB/project") != 0) return 1;
        freopen("/Volumes/FIT-LAB/data/logs/station-ui.log", "a", stderr);
        dup2(fileno(stderr), STDOUT_FILENO);
        PyConfig config;
        PyConfig_InitPythonConfig(&config);
        config.parse_argv = 0;
        PyStatus status = PyConfig_SetString(&config, &config.program_name, L"/Volumes/FIT-LAB/project/.venv/bin/python");
        if (!PyStatus_Exception(status)) status = PyConfig_SetString(&config, &config.run_module, L"master.gui");
        if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
        PyConfig_Clear(&config);
        if (PyStatus_Exception(status)) Py_ExitStatusException(status);
        return Py_RunMain();
    }
}
