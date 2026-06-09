import asyncio
import json
import time
import redis
import websockets

# Cấu hình
WS_URL = "ws://localhost/api/v1/road/ws/violations"
REDIS_URL = "redis://localhost:6379/0"

async def listen_to_ws():
    print(f"[*] Đang kết nối tới NGINX WebSocket: {WS_URL}")
    try:
        # Sử dụng websockets client để kết nối
        async with websockets.connect(WS_URL) as ws:
            print("[+] Đã kết nối thành công WebSocket qua NGINX!")
            print("[*] Đang lắng nghe luồng sự kiện vi phạm...\n")
            
            while True:
                message = await ws.recv()
                data = json.loads(message)
                print("="*60)
                print(" NHẬN ĐƯỢC CẢNH BÁO VI PHẠM TỪ WEBSOCKET 🚨")
                print("="*60)
                print(json.dumps(data, indent=2, ensure_ascii=False))
                print("="*60 + "\n")
                
                # Nhận được 1 tin nhắn test là thành công
                break
                
    except Exception as e:
        print(f"[-] Lỗi WebSocket: {e}")

def publish_fake_violation():
    print("[*] Đang đẩy 1 cảnh báo vi phạm giả lập vào Redis pub/sub...")
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        fake_payload = {
            "camera_id": 1234,
            "camera_name": "Ngã Tư Sở (Mock)",
            "violation_type": "red_light",
            "vehicle_track_id": 999,
            "speed_kmh": 45.5,
            "license_plate": "29A-12345",
            "timestamp": time.time(),
            "evidence_image_url": "http://localhost:9000/traffic-evidence/mock.jpg"
        }
        # Publish tới channel violations:alerts (như AnalyzeOnRoad đang làm)
        r.publish("violations:alerts", json.dumps(fake_payload))
        print("[+] Đã đẩy giả lập thành công!")
    except Exception as e:
        print(f"[-] Lỗi Redis: {e}")

async def main():
    # Khởi chạy listener trong background
    listener_task = asyncio.create_task(listen_to_ws())
    
    # Đợi 2s để đảm bảo WebSocket đã connect
    await asyncio.sleep(2)
    
    # Kích hoạt sự kiện vi phạm
    publish_fake_violation()
    
    # Chờ listener nhận xong hoặc timeout sau 5s
    try:
        await asyncio.wait_for(listener_task, timeout=5.0)
        print("[*] Kịch bản test hoàn tất thành công!")
    except asyncio.TimeoutError:
        print("[-] Timeout: Không nhận được cảnh báo qua WebSocket sau 5 giây.")

if __name__ == "__main__":
    asyncio.run(main())
