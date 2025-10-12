import time
import socket
import sys

def wait_for(host, port, service_name, timeout=60):
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"{service_name} is ready at {host}:{port}")
                return
        except OSError:
            if time.time() - start_time > timeout:
                print(f"Timeout waiting for {service_name} at {host}:{port}")
                sys.exit(1)
            print(f"Waiting for {service_name} at {host}:{port}...")
            time.sleep(1)


if __name__ == "__main__":
    # Adjust these according to your docker-compose service names
    wait_for("postgres", 5432, "Postgres")
    wait_for("redis", 6379, "Redis")
