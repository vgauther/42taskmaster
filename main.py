import sys

class TaskmasterCLI:
    def __init__(self):
        self.running = True
        self.commands = {
            'start': self.start,
            'stop': self.stop,
            'status': self.status,
            'exit': self.exit,
            'help': self.help,
        }

    def run(self):
        while self.running:
            try:
                user_input = input("taskmaster> ").strip()
                if not user_input:
                    continue
                parts = user_input.split()
                command = parts[0]
                args = parts[1:]

                if command in self.commands:
                    self.commands[command](args)
                else:
                    print(f"Unknown command: {command}. Type 'help' for a list.")
            except (EOFError, KeyboardInterrupt):
                print("\nExiting Taskmaster.")
                self.running = False

    def start(self, args):
        print(f"[start] Called with args: {args}")

    def stop(self, args):
        print(f"[stop] Called with args: {args}")

    def status(self, args):
        print("[status] Showing status of processes (not implemented yet).")

    def exit(self, args):
        print("Goodbye!")
        self.running = False

    def help(self, args):
        print("Available commands: start, stop, status, exit, help")

if __name__ == "__main__":
    cli = TaskmasterCLI()
    cli.run()
