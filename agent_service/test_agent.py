"""
Test file cho Flood AI Agent.
Chạy: uv run python test_agent.py
"""

import asyncio
import sys
import httpx

# Fix Windows console encoding for Vietnamese
sys.stdout.reconfigure(encoding="utf-8")

AGENT_URL = "http://localhost:8001"


async def test_health():
    """Test health endpoint."""
    print("=" * 50)
    print("TEST: Health check")
    print("=" * 50)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{AGENT_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        assert response.status_code == 200
        print("[OK] Health check passed!\n")


async def test_chat_stream(message: str):
    """Test chat stream endpoint."""
    print("=" * 50)
    print(f"TEST: Chat stream - '{message}'")
    print("=" * 50)
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{AGENT_URL}/chat/stream",
            json={"message": message},
        ) as response:
            print(f"Status: {response.status_code}")
            print("Streaming response:")
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]  # bỏ "data: "
                    print(f"  -> {data}")
    print("[OK] Chat stream done!\n")


async def test_history():
    """Test history endpoint."""
    print("=" * 50)
    print("TEST: Get history")
    print("=" * 50)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{AGENT_URL}/history")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Messages count: {len(data['messages'])}")
        for msg in data["messages"]:
            role = msg["role"]
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            print(f"  [{role}] {content}")
        print("[OK] History passed!\n")


async def test_reset():
    """Test reset endpoint."""
    print("=" * 50)
    print("TEST: Reset state")
    print("=" * 50)
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{AGENT_URL}/reset")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        assert response.status_code == 200
        print("[OK] Reset passed!\n")


async def main():
    print("\n=== Flood AI Agent Test Suite ===")
    print(f"Target: {AGENT_URL}\n")

    # 1. Health check
    # await test_health()

    # # 2. Reset trước khi test
    # await test_reset()

    # # 3. Chat - hỏi trạng thái camera
    # await test_chat_stream("Đường Nguyễn Hữu Cảnh có bị ngập không?")

    # # 4. Xem history
    # await test_history()

    # # 5. Chat tiếp - hỏi thời tiết
    # await test_chat_stream("Thời tiết hiện tại thế nào?")

    # # 6. History sau 2 câu
    # await test_history()

    # # 7. Reset lại
    # await test_reset()

    # # 8. Kiểm tra history trống
    # await test_history()
    await test_chat_stream("Tình trạng ngập của đường Trường Chinh hiện tại như thế nào?")
    print("\n=== All tests completed! ===")


if __name__ == "__main__":
    asyncio.run(main())
