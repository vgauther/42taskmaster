import yaml
import sys
import subprocess
import shlex

class Taskmaster:
    def __init__(self, config_path):
        self.config_path = config_path
        self.processes = {}
        self.config = {}
        self.load_config()

    def load_config(self):
        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)
            programs = self.config.get("programs", {})
            for name, settings in programs.items():
                if settings.get("autostart", False):
                    self.start([name])

    def start(self, args):
        if not args:
            print("Usage: start <program>")
            return
        name = args[0]
        settings = self.config["programs"].get(name)
        if not settings:
            print(f"[ERROR] Program '{name}' not found.")
            return
        if name in self.processes and self.processes[name].poll() is None:
            print(f"[INFO] Program '{name}' already running (pid={self.processes[name].pid})")
            return
        cmd = settings["cmd"]
        try:
            print(f"[START] {name} -> {cmd}")
            proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes[name] = proc
        except Exception as e:
            print(f"[ERROR] Failed to start '{name}': {e}")

    def stop(self, args):
        if not args:
            print("Usage: stop <program>")
            return
        name = args[0]
        proc = self.processes.get(name)
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait()
            print(f"[STOP] {name} stopped.")
        else:
            print(f"[INFO] Program '{name}' is not running.")

    def restart(self, args):
        self.stop(args)
        self.start(args)

    def status(self, args=None):
        for name in self.config["programs"]:
            proc = self.processes.get(name)
            if proc and proc.poll() is None:
                print(f"{name}: RUNNING (pid={proc.pid})")
            else:
                print(f"{name}: STOPPED")

    def run_shell(self):
        print("Taskmaster CLI. Type 'help' for commands.")
        while True:
            try:
                line = input("taskmaster> ").strip()
                if not line:
                    continue
                parts = line.split()
                cmd = parts[0]
                args = parts[1:]

                if cmd == "exit":
                    print("Exiting.")
                    self.cleanup()
                    break
                elif cmd == "start":
                    self.start(args)
                elif cmd == "stop":
                    self.stop(args)
                elif cmd == "restart":
                    self.restart(args)
                elif cmd == "status":
                    self.status()
                elif cmd == "help":
                    print("Commands: start <name>, stop <name>, restart <name>, status, exit")
                else:
                    print(f"[ERROR] Unknown command '{cmd}'.")
            except (EOFError, KeyboardInterrupt):
                print("\n[INFO] Exiting.")
                self.cleanup()
                break

    def cleanup(self):
        for name, proc in self.processes.items():
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
                print(f"[CLEANUP] Stopped '{name}'.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 taskmaster.py config.yaml")
        sys.exit(1)

    tm = Taskmaster(sys.argv[1])
    tm.run_shell()
