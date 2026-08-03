# Jarvis Self-Evolution: Blockchain & Smart Contracts
import hashlib
import time

class Block:
    def __init__(self, index, previous_hash, timestamp, data, hash):
        self.index = index
        self.previous_hash = previous_hash
        self.timestamp = timestamp
        self.data = data
        self.hash = hash

def calculate_hash(index, previous_hash, timestamp, data):
    value = str(index) + str(previous_hash) + str(timestamp) + str(data)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def create_genesis_block():
    return Block(0, "0", int(time.time()), "Genesis Block by Jarvis", calculate_hash(0, "0", int(time.time()), "Genesis Block by Jarvis"))

print("🔗 Jarvis Blockchain Initialized!")
genesis = create_genesis_block()
print(f"Block 0 Hash: {genesis.hash}")
