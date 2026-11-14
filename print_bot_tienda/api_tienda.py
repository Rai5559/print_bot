from fastapi import FastAPI, UploadFile, File, Form
import uvicorn
import subprocess
import os
import json
import shutil

app = FastAPI(title="Servidor de Impresión Local")

# ================= AJUSTES EDITABLES =================
# Si cambias de impresora, solo edita el nombre aquí (debe coincidir con el Panel de Control)
NOMBRE_IMPRESORA = "Canon Maxify GX7110" 
PUERTO_API = 8000
# ===================================================

# Rutas dinámicas: El script siempre sabrá dónde está, sin importar si lo mueves de PC
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUMATRA_PATH = os.path.join(BASE_DIR, "SumatraPDF", "SumatraPDF.exe")
RUTA_TRABAJOS = os.path.join(BASE_DIR, "trabajos_recibidos")

os.makedirs(RUTA_TRABAJOS, exist_ok=True)

@app.post("/imprimir")
async def recibir_e_imprimir(archivo: UploadFile = File(...), config: str = Form(...)):
    ruta_local = os.path.join(RUTA_TRABAJOS, archivo.filename)
    
    with open(ruta_local, "wb") as buffer:
        shutil.copyfileobj(archivo.file, buffer)
        
    conf = json.loads(config)
    ajustes = []
    
    # Color / Blanco y Negro
    if conf.get("color") is False:
        ajustes.append("monochrome")
    else:
        ajustes.append("color")
        
    # Doble cara
    if conf.get("doble_cara"):
        ajustes.append("duplex")
        
    # Tamaño y Bandeja
    if conf.get("tamano_papel") == "oficio":
        ajustes.append("paper=legal")
        ajustes.append("bin=rear") 
    else:
        ajustes.append("paper=letter")
        
    if conf.get("tipo_papel") == "fotografico":
        ajustes.append("bin=rear")
        
    string_ajustes = ",".join(ajustes)
    
    comando = [
        SUMATRA_PATH,
        "-print-to", NOMBRE_IMPRESORA,
        "-print-settings", string_ajustes,
        "-silent", 
        ruta_local
    ]
    
    try:
        subprocess.Popen(comando)
        return {"status": "ok", "mensaje": "Impresión iniciada"}
    except Exception as e:
        return {"status": "error", "mensaje": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PUERTO_API)