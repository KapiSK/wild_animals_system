import requests
import sys

def check_connection(server_ip):
    url = f"http://{server_ip}:8000/upload"
    print(f"Testing connection to {url} ...")
    
    # Dummy image data
    files = {'file': ('test.txt', b'Hello World')}
    headers = {'X-Seq-Num': '0', 'X-Rssi': '-50'}
    
    try:
        response = requests.post(url, files=files, headers=headers, timeout=5)
        if response.status_code == 200:
            print("[SUCCESS] Connection established! Server replied with 200 OK.")
            print(f"Response: {response.json()}")
            return True
        else:
            print(f"[FAILED] Server replied with status code: {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        print("[FAILED] Connection timed out. Check IP address and generic network connectivity.")
        return False
    except requests.exceptions.ConnectionError:
        print("[FAILED] Connection refused. Is the server running? Is the IP correct?")
        return False
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_connection.py <PI_IP_ADDRESS>")
        print("Example: python check_connection.py 192.168.1.10")
        
        # Interactive mode
        ip = input("Enter Pi Server IP address: ").strip()
        if ip:
            check_connection(ip)
    else:
        check_connection(sys.argv[1])
