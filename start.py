"""
SLB Tracking Mechanism - Main Entry Point

Runs both the scraper and Flask dashboard concurrently.
"""

import sys
import subprocess
import time
from pathlib import Path

# Store process references for cleanup
processes = []

def main():
    """Main entry point - starts both scraper and dashboard"""

    print("""
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║           📈 SLB Tracking Mechanism - Starting... 📈               ║
║                                                                    ║
║   - Scraper: Fetches data every 5 mins (9:15 AM - 5:00 PM)        ║
║   - Dashboard: http://localhost:5000                               ║
║                                                                    ║
║   Press Ctrl+C to stop both                                        ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
    """)

    script_dir = Path(__file__).parent

    # Start scraper
    print("=" * 80)
    print("Starting SLB Scraper...")
    print("=" * 80)
    scraper_process = subprocess.Popen(
        [sys.executable, "slb_pw.py"],
        cwd=script_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )
    processes.append(scraper_process)
    print(f"Scraper started (PID: {scraper_process.pid})")

    # Wait a moment for scraper to initialize
    time.sleep(3)

    # Start Static Server (replaces Flask dashboard)
    print("\n" + "=" * 80)
    print("Starting Local Static Server...")
    print("=" * 80)
    print("Dashboard will be available at: http://localhost:8000/templates/dashboard.html")
    print("=" * 80)

    # Use http.server to serve the current directory
    dashboard_process = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8000"],
        cwd=script_dir,
        stdout=None,  # Don't capture stdout, let it show directly
        stderr=None   # Don't capture stderr, let it show directly
    )
    processes.append(dashboard_process)
    print(f"Static Server started (PID: {dashboard_process.pid})")

    print("\n" + "=" * 80)
    print("✅ All services are running!")
    print("📊 Open your browser and navigate to: http://localhost:8000/templates/dashboard.html")
    print("=" * 80)
    print("\nWaiting... Press Ctrl+C to stop all services\n")

    # Monitor processes
    try:
        # Track which processes we've already warned about
        exited_processes = set()
        while True:
            # Check if processes are still running
            for i, proc in enumerate(processes):
                if proc.poll() is not None and i not in exited_processes:
                    print(f"\n⚠️  Process {i+1} exited unexpectedly (exit code: {proc.returncode})")
                    exited_processes.add(i)

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n" + "=" * 80)
        print("Shutting down SLB Tracking Mechanism...")
        print("=" * 80)

        # Terminate all processes
        for proc in processes:
            if proc.poll() is None:  # Still running
                print(f"Stopping process (PID: {proc.pid})...")
                proc.terminate()

        # Wait for processes to terminate
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"Force killing process (PID: {proc.pid})...")
                proc.kill()

        print("All services stopped.")
        print("=" * 80)

if __name__ == "__main__":
    main()
