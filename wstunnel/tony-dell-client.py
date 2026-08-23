import asyncio
import os
import sys

try:
    import websockets
except ImportError:
    print("Error: websockets is not installed.")
    print("Run: pip3 install --user websockets")
    sys.exit(1)

SERVER = os.environ.get('TUNNEL_SERVER', 'wss://chaba.h3.gizmo-thailand.com/tunnel/tony-dell')
LOCAL_HOST = os.environ.get('LOCAL_HOST', '127.0.0.1')
LOCAL_PORT = int(os.environ.get('LOCAL_PORT', '22'))


async def tcp_to_ws(reader, websocket):
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            await websocket.send(data)
    except asyncio.CancelledError:
        pass


async def ws_to_tcp(websocket, writer):
    try:
        async for data in websocket:
            writer.write(data)
            await writer.drain()
    except asyncio.CancelledError:
        pass


async def handle_connection(websocket):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LOCAL_HOST, LOCAL_PORT),
            timeout=5
        )
    except Exception as e:
        print(f"cannot connect to {LOCAL_HOST}:{LOCAL_PORT}: {e}")
        return
    try:
        await asyncio.gather(
            tcp_to_ws(reader, websocket),
            ws_to_tcp(websocket, writer)
        )
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    while True:
        try:
            async with websockets.connect(SERVER) as websocket:
                print('connected to tunnel server')
                await handle_connection(websocket)
        except Exception as e:
            print(f'connection error: {e}')
        await asyncio.sleep(5)


if __name__ == '__main__':
    asyncio.run(main())
