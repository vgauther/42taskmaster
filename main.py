import yaml
import sys
import subprocess
import shlex
import os
import signal
import threading
import time
import logging
from dotenv import load_dotenv

# Configuration de base du logger global
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("taskmaster.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class Taskmaster:
    def __init__(self, config_path):
        self.config_path = config_path
        self.processes = {}  # Clé : "name:index", Valeur : Popen
        self.retry_count = {}  # Clé : "name:index", Valeur : nombre de tentatives
        self.started_ok = {}  # Clé : "name:index", Valeur : bool indiquant si le process a bien démarré
        self.config = {}
        load_dotenv()  # Chargement des variables d'environnement depuis un .env si présent
        self.load_config()
        threading.Thread(target=self.monitor_processes, daemon=True).start()
        self.config_mtime = os.path.getmtime(self.config_path)
        threading.Thread(target=self.watch_config_file, daemon=True).start()
        signal.signal(signal.SIGHUP, self.reload_config)  # Support du SIGHUP pour recharger la configuration à chaud

    def load_config(self):
        with open(self.config_path, 'r') as f:
            new_config = yaml.safe_load(f)
            new_programs = new_config.get("programs", {})
            old_programs = set(self.config.get("programs", {}).keys())
            self.config = new_config
            new_program_keys = set(new_programs.keys())
            for removed_prog in old_programs - new_program_keys:
                self.stop([removed_prog])
            for name, settings in new_programs.items():
                if settings.get("autostart", False):
                    self.start([name])

    def reload_config(self, *args):
        logger.info("Reloading configuration via SIGHUP or command...")
        self.load_config()
        logger.info("Configuration reloaded.")
        print("taskmaster> ", end="", flush=True)

    def watch_config_file(self):
        while True:
            try:
                current_mtime = os.path.getmtime(self.config_path)
                if current_mtime != self.config_mtime:
                    self.config_mtime = current_mtime
                    self.reload_config()
            except Exception as e:
                logger.warning(f"Failed to watch config file: {e}")
            time.sleep(1)

    def ensure_log_file(self, path):
        if path and path != os.devnull:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                open(path, 'a').close()

    def monitor_processes(self):
        while True:
            for key in list(self.processes.keys()):
                proc = self.processes[key]
                if proc.poll() is not None:
                    name, idx = key.split(":")
                    settings = self.config["programs"][name]
                    exitcodes = settings.get("exitcodes", [0])
                    autorestart = settings.get("autorestart", "never")
                    retries = settings.get("startretries", 0)
                    retcode = proc.returncode
                    is_expected_exit = retcode in exitcodes
                    should_restart = False
                    if autorestart == "always":
                        should_restart = True
                    elif autorestart == "unexpected" and not is_expected_exit:
                        should_restart = True
                    if should_restart:
                        started_ok = self.started_ok.get(key, False)
                        if not started_ok and self.retry_count.get(key, 0) < retries:
                            current_retry = self.retry_count.get(key, 0)
                            logger.warning(f"[RETRY] Attempt {current_retry + 1} for {key}")
                            self.retry_count[key] = current_retry + 1
                            if not self._restart_process(key, settings):
                                time.sleep(1)
                        elif started_ok:
                            self.retry_count[key] = 0
                            self._restart_process(key, settings)
                        else:
                            logger.error(f"[GIVEUP] {key} reached max retries ({retries})")
                            del self.processes[key]
                            self.retry_count.pop(key, None)
                            self.started_ok.pop(key, None)
                    else:
                        logger.info(f"{key} exited with code {retcode} (expected={is_expected_exit})")
                        del self.processes[key]
                        self.retry_count.pop(key, None)
                        self.started_ok.pop(key, None)
            time.sleep(1)

    def _restart_process(self, key, settings):
        try:
            self.ensure_log_file(settings.get("stdout"))
            self.ensure_log_file(settings.get("stderr"))
            stdout = open(settings.get("stdout", os.devnull), "ab")
            stderr = open(settings.get("stderr", os.devnull), "ab")
            umask_str = settings.get("umask")
            umask_value = int(umask_str, 8) if umask_str else None
            old_umask = os.umask(umask_value) if umask_value is not None else None
            try:
                env = os.environ.copy()
                env.update(settings.get("env", {}))
                workingdir = settings.get("workingdir", None)
                new_proc = subprocess.Popen(
                    shlex.split(settings["cmd"]),
                    stdout=stdout,
                    stderr=stderr,
                    cwd=workingdir,
                    env=env
                )
            finally:
                if old_umask is not None:
                    os.umask(old_umask)
            self.processes[key] = new_proc
            logger.info(f"[RESTART] {key} (pid={new_proc.pid})")
            return True
        except Exception as e:
            logger.error(f"Failed to restart {key}: {e}")
            return False

    def start(self, args):
        if not args:
            logger.warning("Usage: start <program>")
            return
        name = args[0]
        settings = self.config["programs"].get(name)
        if not settings:
            logger.error(f"Program '{name}' not found.")
            return
        cmd = settings["cmd"]
        numprocs = settings.get("numprocs", 1)
        startsecs = settings.get("startsecs", 0)
        for i in range(numprocs):
            key = f"{name}:{i}"
            if key in self.processes and self.processes[key].poll() is None:
                logger.info(f"{key} already running (pid={self.processes[key].pid})")
                continue
            try:
                self.ensure_log_file(settings.get("stdout"))
                self.ensure_log_file(settings.get("stderr"))
                stdout = open(settings.get("stdout", os.devnull), "ab")
                stderr = open(settings.get("stderr", os.devnull), "ab")
                umask_str = settings.get("umask")
                umask_value = int(umask_str, 8) if umask_str else None
                old_umask = os.umask(umask_value) if umask_value is not None else None
                try:
                    env = os.environ.copy()
                    env.update(settings.get("env", {}))
                    workingdir = settings.get("workingdir", None)
                    proc = subprocess.Popen(
                        shlex.split(cmd),
                        stdout=stdout,
                        stderr=stderr,
                        cwd=workingdir,
                        env=env
                    )
                finally:
                    if old_umask is not None:
                        os.umask(old_umask)
                logger.info(f"[START] {key} launched (pid={proc.pid}), waiting {startsecs}s...")
                time.sleep(startsecs)
                if proc.poll() is not None:
                    logger.warning(f"[FAIL] {key} exited too soon (code={proc.returncode})")
                    self.processes[key] = proc
                    self.retry_count[key] = 1
                    self.started_ok[key] = False
                    continue
                self.processes[key] = proc
                self.retry_count[key] = 0
                self.started_ok[key] = True
                logger.info(f"[OK] {key} is now running (pid={proc.pid})")
            except Exception as e:
                logger.error(f"Failed to start '{key}': {e}")

    def stop(self, args):
        if not args:
            logger.warning("Usage: stop <program>")
            return
        name = args[0]
        for key in list(self.processes.keys()):
            if key.startswith(name + ":"):
                proc = self.processes[key]
                if proc.poll() is None:
                    settings = self.config["programs"].get(name, {})
                    stopsignal = settings.get("stopsignal", "TERM").upper()
                    stoptime = settings.get("stoptime", 5)
                    sig = getattr(signal, f"SIG{stopsignal}", signal.SIGTERM)
                    try:
                        proc.send_signal(sig)
                        logger.info(f"[STOP] Sent {stopsignal} to '{key}', waiting {stoptime}s...")
                        proc.wait(timeout=stoptime)
                    except subprocess.TimeoutExpired:
                        logger.warning(f"[KILL] {key} did not stop after {stoptime}s, killing.")
                        proc.kill()
                        proc.wait()
                    logger.info(f"[STOP] {key} stopped.")
                else:
                    logger.info(f"[INFO] {key} is not running.")
                del self.processes[key]
                self.retry_count.pop(key, None)

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
                    logger.info(f"{key}: RUNNING (pid={proc.pid})")
                else:
                    logger.info(f"{key}: STOPPED")

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
                elif cmd == "reload":
                    self.reload_config()
                elif cmd == "help":
                    print("Commands: start <name>, stop <name>, restart <name>, status, reload, exit")
                else:
                    logger.error(f"Unknown command '{cmd}'.")
            except (EOFError, KeyboardInterrupt):
                print("\n[INFO] Exiting.")
                self.cleanup()
                break

    def cleanup(self):
        for key, proc in self.processes.items():
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
                logger.info(f"[CLEANUP] Stopped '{key}'.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 taskmaster.py config.yaml")
        sys.exit(1)
    tm = Taskmaster(sys.argv[1])
    tm.run_shell()
