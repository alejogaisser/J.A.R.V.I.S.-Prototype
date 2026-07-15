import subprocess
import sys

print("Installing requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

print("Installing Playwright browsers...")
subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

print("\n✅ Setup complete!")
print("Direct mode: python jarvis_launcher.py --mode direct")
print("Wake-word mode: python jarvis_launcher.py --mode wake")

