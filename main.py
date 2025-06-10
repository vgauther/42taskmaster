import yaml
import sys
import subprocess
import shlex
import os
import signal
import threading
import time

class Taskmaster:
    def __init__(self, config_path):
        self.config_path = config_path
        self.processes = {}  # Clé : "name:index", Valeur : Popen
        self.config = {}
        self.load_config()
        threading.Thread(target=self.monitor_processes, daemon=True).start()
        self.config_mtime = os.path.getmtime(self.config_path)
        threading.Thread(target=self.watch_config_file, daemon=True).start()

    def load_config(self):
        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)
            programs = self.config.get("programs", {})
            for name, settings in programs.items():
                if settings.get("autostart", False):
                    self.start([name])

    def reload_config(self, *args):
        print("\n[INFO] Reloading configuration...")
        self.load_config()
        print("[INFO] Configuration reloaded.\ntaskmaster> ", end="", flush=True)

    def watch_config_file(self):
        while True:
            try:
                current_mtime = os.path.getmtime(self.config_path)
                if current_mtime != self.config_mtime:
                    self.config_mtime = current_mtime
                    self.reload_config()
            except Exception as e:
                print(f"[WARN] Failed to watch config file: {e}")
            time.sleep(1)  # Vérifie toutes les secondes

    def monitor_processes(self):
        while True:
            for key in list(self.processes.keys()):
                proc = self.processes[key]
                if proc.poll() is not None:  # Processus terminé
                    name, idx = key.split(":")
                    settings = self.config["programs"][name]

                    exitcodes = settings.get("exitcodes", [0])  # Codes "attendus"
                    autorestart = settings.get("autorestart", "never")
                    retries = settings.get("startretries", 0)

                    retcode = proc.returncode

                    # Détermine si la sortie est "attendue"
                    is_expected_exit = retcode in exitcodes

                    should_restart = False

                    if autorestart == "always":
                        should_restart = True
                    elif autorestart == "unexpected" and not is_expected_exit:
                        should_restart = True

                    if should_restart:
                        if retries > 0:
                            for attempt in range(retries):
                                try:
                                    stdout = open(settings.get("stdout", os.devnull), "ab")
                                    stderr = open(settings.get("stderr", os.devnull), "ab")
                                    new_proc = subprocess.Popen(shlex.split(settings["cmd"]),
                                                                stdout=stdout,
                                                                stderr=stderr)
                                    self.processes[key] = new_proc
                                    print(f"[RESTART] {key} (pid={new_proc.pid})")
                                    break
                                except Exception as e:
                                    print(f"[RETRY {attempt+1}] Failed to restart {key}: {e}")
                                    time.sleep(1)
                        else:
                            try:
                                stdout = open(settings.get("stdout", os.devnull), "ab")
                                stderr = open(settings.get("stderr", os.devnull), "ab")
                                new_proc = subprocess.Popen(shlex.split(settings["cmd"]),
                                                            stdout=stdout,
                                                            stderr=stderr)
                                self.processes[key] = new_proc
                                print(f"[RESTART] {key} (pid={new_proc.pid})")
                            except Exception as e:
                                print(f"[ERROR] Failed to restart {key}: {e}")
                    else:
                        print(f"[INFO] {key} exited with code {retcode} (expected={is_expected_exit})")
                        del self.processes[key]
            time.sleep(1)

    def start(self, args):
        if not args:
            print("Usage: start <program>")
            return

        name = args[0]
        settings = self.config["programs"].get(name)

        if not settings:
            print(f"[ERROR] Program '{name}' not found.")
            return

        cmd = settings["cmd"]
        numprocs = settings.get("numprocs", 1)
        startsecs = settings.get("startsecs", 0)

        for i in range(numprocs):
            key = f"{name}:{i}"

            # Vérifie si le processus tourne déjà
            if key in self.processes and self.processes[key].poll() is None:
                print(f"[INFO] {key} already running (pid={self.processes[key].pid})")
                continue

            try:
                # Récupère les chemins stdout/stderr s'ils existent, sinon /dev/null
                stdout = open(settings.get("stdout", os.devnull), "ab")
                stderr = open(settings.get("stderr", os.devnull), "ab")

                # Démarre le processus
                proc = subprocess.Popen(
                    shlex.split(cmd),
                    stdout=stdout,
                    stderr=stderr
                )
                print(f"[START] {key} launched (pid={proc.pid}), waiting {startsecs}s...")

                # Attente pour valider que le process reste en vie
                time.sleep(startsecs)

                # Vérifie si le process est encore actif
                if proc.poll() is not None:
                    print(f"[FAIL] {key} exited too soon (code={proc.returncode})")
                    continue

                # Ajoute le process à la liste s'il est OK
                self.processes[key] = proc
                print(f"[OK] {key} is now running (pid={proc.pid})")

            except Exception as e:
                print(f"[ERROR] Failed to start '{key}': {e}")

    def stop(self, args):
        if not args:
            print("Usage: stop <program>")
            return
        name = args[0]
        for key in list(self.processes.keys()):
            if key.startswith(name + ":"):
                proc = self.processes[key]
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait()
                    print(f"[STOP] {key} stopped.")
                else:
                    print(f"[INFO] {key} is not running.")

    def restart(self, args):
        self.stop(args)
        self.start(args)

    def status(self, args=None):
        for name, settings in self.config["programs"].items():
            numprocs = settings.get("numprocs", 1)
            for i in range(numprocs):
                key = f"{name}:{i}"
                proc = self.processes.get(key)
                if proc and proc.poll() is None:
                    print(f"{key}: RUNNING (pid={proc.pid})")
                else:
                    print(f"{key}: STOPPED")

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
        for key, proc in self.processes.items():
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
                print(f"[CLEANUP] Stopped '{key}'.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 taskmaster.py config.yaml")
        sys.exit(1)

    tm = Taskmaster(sys.argv[1])
    tm.run_shell()
