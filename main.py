import yaml
import sys
import subprocess

class Taskmaster:
    def __init__(self, config_path):
        self.processes = {}
        self.load_config(config_path)

    def load_config(self, path):
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
            programs = config.get("programs", {})
            for name, settings in programs.items():
                cmd = settings.get("cmd")
                autostart = settings.get("autostart", False)
                if cmd and autostart:
                    print(f"[INFO] Autostarting '{name}' -> {cmd}")
                    process = subprocess.Popen(cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.processes[name] = process
                else:
                    print(f"[SKIP] '{name}' not started (autostart={autostart})")

    def status(self):
        print("=== Process status ===")
        for name, proc in self.processes.items():
            if proc.poll() is None:
                print(f"{name}: RUNNING (pid={proc.pid})")
            else:
                print(f"{name}: STOPPED")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 taskmaster.py config.yaml")
        sys.exit(1)

    tm = Taskmaster(sys.argv[1])
    tm.status()
