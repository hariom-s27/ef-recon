import ollama, numpy as np

def embed(text):
    return np.array(ollama.embeddings(model="nomic-embed-text", prompt=text)["embedding"])

def similarity(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

diesel   = embed("diesel")
hsd      = embed("HSD high speed diesel")
elec     = embed("grid electricity")

print("diesel vs HSD :", round(similarity(diesel, hsd), 3))    # expect HIGH (~0.7-0.9)
print("diesel vs elec:", round(similarity(diesel, elec), 3))   # expect LOW