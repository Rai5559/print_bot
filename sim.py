import os
import sys
import time
import shutil
import asyncio
import importlib.util
import numpy as np
from datetime import datetime, timedelta
from PIL import Image, ImageDraw
import pymupdf as fitz
import pandas as pd

# =====================================================================
# CARGA AUTOMÁTICA DE TU ARCHIVO PRINCIPAL (main_2.py o main.py)
# =====================================================================
archivo_objetivo = "main_2.py" if os.path.exists("main_2.py") else "main.py"
print(f"📦 Importando motor desde: {archivo_objetivo}...")

spec = importlib.util.spec_from_file_location("modulo_cerebro", archivo_objetivo)
cerebro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cerebro)

CARPETA_PRUEBAS = "PRUEBAS_SISTEMA_V2"

def crear_archivos_de_prueba():
    """Genera imágenes de distintos tamaños, un documento con sombra y un PDF de 12 páginas."""
    os.makedirs("temp_test_files", exist_ok=True)
    archivos_img = []
    
    # 1. Crear 8 imágenes de diferentes tamaños y proporciones
    colores = [
        (220, 50, 50), (50, 100, 220), (40, 180, 99), (230, 126, 34),
        (142, 68, 173), (22, 160, 133), (211, 84, 0), (44, 62, 80)
    ]
    tamanos = [
        (800, 600), (450, 900), (1200, 900), (500, 500),
        (850, 550), (600, 800), (1000, 1000), (350, 750)
    ]
    
    for i in range(8):
        img = Image.new('RGB', tamanos[i], color=colores[i])
        d = ImageDraw.Draw(img)
        # Dibujar marco blanco y etiqueta para distinguir orientación
        d.rectangle([15, 15, tamanos[i][0]-15, tamanos[i][1]-15], outline="white", width=6)
        d.text((40, 40), f"FOTO #{i+1}\n{tamanos[i][0]}x{tamanos[i][1]}", fill="white")
        ruta = f"temp_test_files/foto_{i+1}.jpg"
        img.save(ruta)
        archivos_img.append(ruta)
        
    # 2. Crear un documento falso con SOMBRA ASIMÉTRICA (para probar OpenCV Modo Escáner)
    ancho_doc, alto_doc = 1000, 1400
    # Gradiente de gris oscuro (90) a gris claro (210) simulando sombra de celular
    gradiente = np.linspace(90, 210, alto_doc, dtype=np.uint8)
    fondo_sombra = np.tile(gradiente[:, None], (1, ancho_doc))
    img_sombra = Image.fromarray(fondo_sombra).convert("RGB")
    
    d_doc = ImageDraw.Draw(img_sombra)
    d_doc.text((100, 150), "ACTA / RECIBO CON SOMBRA DE CELULAR", fill=(15, 15, 15))
    for linea in range(250, 1250, 90):
        d_doc.text((100, linea), f"Línea de texto de prueba #{linea} - Consumo de tinta...", fill=(25, 25, 25))
        d_doc.line([(100, linea+35), (900, linea+35)], fill=(40, 40, 40), width=2)
        
    ruta_sombra = "temp_test_files/recibo_con_sombra.jpg"
    img_sombra.save(ruta_sombra)

    # 3. Crear un PDF pesado de 12 páginas
    ruta_pdf = "temp_test_files/manual_12_paginas.pdf"
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page()
        page.insert_text((100, 150), f"DOCUMENTO DE PRUEBA - PÁGINA {i+1} DE 12", fontsize=18)
        # Añadir un rectángulo de color en algunas páginas para probar el detector de tinta
        if (i + 1) in [2, 4, 8]:
            page.draw_rect(fitz.Rect(100, 200, 400, 400), color=(0, 0.4, 0.8), fill=(0, 0.4, 0.8))
    doc.save(ruta_pdf)
    doc.close()
    
    return archivos_img, ruta_sombra, ruta_pdf

async def probar_limpieza_disco():
    """Simula archivos viejos y recientes para verificar que el recolector borre solo lo caducado."""
    print("▶️ Ejecutando Test 10: Limpieza Automática de Disco (>24h y >15 días)")
    os.makedirs("temp_uploads", exist_ok=True)
    
    archivo_viejo = os.path.join("temp_uploads", "orden_abandonada_30h.tmp")
    archivo_nuevo = os.path.join("temp_uploads", "orden_reciente_1h.tmp")
    
    with open(archivo_viejo, "w") as f: f.write("basura")
    with open(archivo_nuevo, "w") as f: f.write("activo")
    
    # Alterar la fecha de modificación del archivo viejo a hace 30 horas
    hace_30_horas = time.time() - (30 * 3600)
    os.utime(archivo_viejo, (hace_30_horas, hace_30_horas))
    
    # Crear carpeta histórica de hace 20 días y una de hoy
    fecha_20_dias = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    
    ruta_vieja = os.path.join(cerebro.BASE_DIR, fecha_20_dias, "uuid_viejo")
    ruta_hoy = os.path.join(cerebro.BASE_DIR, fecha_hoy, "uuid_activo")
    os.makedirs(ruta_vieja, exist_ok=True)
    os.makedirs(ruta_hoy, exist_ok=True)
    
    # Ejecutar la función real de tu código
    await cerebro.tarea_mantenimiento_y_limpieza()
    
    exito_temp = (not os.path.exists(archivo_viejo)) and os.path.exists(archivo_nuevo)
    exito_hist = (not os.path.exists(os.path.join(cerebro.BASE_DIR, fecha_20_dias))) and os.path.exists(ruta_hoy)
    
    # Limpiar los señuelos restantes
    if os.path.exists(archivo_nuevo): os.remove(archivo_nuevo)
    if os.path.exists(ruta_hoy): shutil.rmtree(ruta_hoy)
    
    if exito_temp and exito_hist:
        print("   ✅ ÉXITO: Se borraron los temporales >24h y carpetas >15 días, conservando los archivos del día.\n")
    else:
        print(f"   ❌ FALLO en limpieza: Temp OK={exito_temp}, Hist OK={exito_hist}\n")

async def ejecutar_bateria_completa():
    print("🧹 Preparando entorno de pruebas V2...")
    if os.path.exists(CARPETA_PRUEBAS):
        shutil.rmtree(CARPETA_PRUEBAS)
    os.makedirs(CARPETA_PRUEBAS)

    fotos, recibo_sombra, pdf_12pags = crear_archivos_de_prueba()

    casos = [
        {
            "id": "01_Cuadricula_3_Fotos",
            "archivos": fotos[0:3],
            "config": {"layout_n_up": 3, "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "Cuadrícula 2x2 con 3 fotos a color."
        },
        {
            "id": "02_INE_Contraste_Mejorado",
            "archivos": [fotos[0], fotos[1]], # Una horizontal (800x600) y una vertical (450x900)
            "config": {"tipo_documento": "ine", "escala_porcentaje": 100, "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "Acuesta la foto vertical, aplica autocontraste +20% brillo y centra ambas."
        },
        {
            "id": "03_INE_Ampliada_200pct",
            "archivos": [fotos[0], fotos[1]],
            "config": {"tipo_documento": "ine", "escala_porcentaje": 200, "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "Credencial ampliada al 200%."
        },
        {
            "id": "04_Planilla_6_Infantiles",
            "archivos": [fotos[3]],
            "config": {"modo_planilla": True, "dimensiones_cm": [2.5, 3.0], "repeticiones": 6, "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "6 fotos tamaño infantil (2.5x3.0 cm) ancladas en la esquina superior izquierda."
        },
        {
            "id": "05_Planilla_Llenar_Hoja_5x5",
            "archivos": [fotos[2]],
            "config": {"modo_planilla": True, "dimensiones_cm": [5.0, 5.0], "repeticiones": 0, "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "Cálculo automático para llenar toda la hoja carta con cuadros de 5x5 cm."
        },
        {
            "id": "06_Rango_Sucio_Regex",
            "archivos": [pdf_12pags],
            "config": {"rango_paginas": "páginas 2 a la 4 y 8, 11-12", "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "Filtro Regex: de 12 páginas, debe extraer exactamente 6 páginas (2, 3, 4, 8, 11 y 12)."
        },
        {
            "id": "07_Modo_Tetris_BinPacking",
            "archivos": fotos[0:8],
            "config": {"modo_tetris": True, "tamano_papel": "carta", "orientacion": "vertical", "color": True},
            "desc": "Acomodo matemático rectpack de 8 fotos sin deformar tamaño original."
        },
        {
            "id": "08_HTML_Blindado_Oficio_Horizontal",
            "archivos": fotos[0:3],
            "config": {
                "modo_html": True,
                "tamano_papel": "oficio",
                "orientacion": "horizontal",
                "color": True,
                # Incluimos un <script> malicioso y una imagen externa para probar el cortafuegos
                "codigo_html": """
                <script>alert('hack');</script>
                <div style='display:flex; width:100vw; height:100vh; padding:20px; gap:15px; box-sizing:border-box;'>
                    <div style='flex:2; height:100%;'><img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'></div>
                    <div style='flex:1; display:flex; flex-direction:column; gap:15px; height:100%;'>
                        <img src='{img_1}' style='width:100%; height:50%; object-fit:contain;'>
                        <img src='{img_2}' style='width:100%; height:50%; object-fit:contain;'>
                    </div>
                </div>
                """
            },
            "desc": "Playwright en papel Oficio Horizontal, limpiando <script> y bloqueando red."
        },
        {
            "id": "09_Modo_Escaner_OpenCV_Sombra",
            "archivos": [recibo_sombra],
            "config": {"modo_escaner": True, "tamano_papel": "carta", "orientacion": "vertical", "color": False},
            "desc": "Umbral adaptativo OpenCV: convierte un recibo con sombra gris oscura en blanco puro."
        }
    ]

    print("\n🚀 INICIANDO BATERÍA DE PRUEBAS DE RENDERIZADO Y COSTOS...\n")
    
    for c in casos:
        ruta_out = os.path.join(CARPETA_PRUEBAS, c["id"])
        os.makedirs(ruta_out, exist_ok=True)
        print(f"▶️ Ejecutando {c['id']}: {c['desc']}")
        
        try:
            # 1. Generar el PDF
            pdf_generado = await cerebro.unificar_y_procesar_a_pdf(c["archivos"], ruta_out, c["config"])
            
            # 2. Probar la calculadora de costos de tinta sobre el PDF resultante
            costos = cerebro.calcular_costo_gx7110(pdf_generado, c["config"])
            
            # 3. Registrar en CSV de prueba
            cerebro.guardar_registro_csv(c["id"][:8], c["config"], costos)
            
            doc_check = fitz.open(pdf_generado)
            num_pags = len(doc_check)
            doc_check.close()
            
            print(f"   ✅ PDF OK ({num_pags} págs) -> Cobro sugerido: ${costos['precio_venta_sugerido']} MXN | Costo int: ${costos['costo_interno_mxn']} MXN")
            print(f"   📊 Desglose tinta: B/N={costos['resumen_tipos']['texto_bn']}, Color={costos['resumen_tipos']['texto_color']}, Full={costos['resumen_tipos']['imagen_full']}\n")
        except Exception as e:
            print(f"   ❌ ERROR en {c['id']}: {e}\n")

    # Comparación directa de ahorro de tinta con el Modo Escáner
    print("🔍 COMPARATIVA DE AHORRO DE TINTA (MODO ESCÁNER):")
    ruta_sin_filtro = os.path.join(CARPETA_PRUEBAS, "09_Comparativa_Sin_Escaner")
    os.makedirs(ruta_sin_filtro, exist_ok=True)
    pdf_sucio = await cerebro.unificar_y_procesar_a_pdf([recibo_sombra], ruta_sin_filtro, {"modo_escaner": False, "color": False})
    
    doc_sucio = fitz.open(pdf_sucio)
    _, cob_bn_sucio = cerebro.analizar_cobertura_pagina(doc_sucio[0])
    doc_sucio.close()
    
    pdf_limpio = os.path.join(CARPETA_PRUEBAS, "09_Modo_Escaner_OpenCV_Sombra", "documento_final.pdf")
    doc_limpio = fitz.open(pdf_limpio)
    _, cob_bn_limpio = cerebro.analizar_cobertura_pagina(doc_limpio[0])
    doc_limpio.close()
    
    print(f"   📉 Mancha de tinta SIN Modo Escáner: {cob_bn_sucio*100:.1f}% de la hoja")
    print(f"   ✨ Mancha de tinta CON Modo Escáner: {cob_bn_limpio*100:.1f}% de la hoja\n")

    # Probar Limpieza de Disco
    await probar_limpieza_disco()

    # Probar Generación de Excel desde el CSV
    print("▶️ Ejecutando Test 11: Generación de Reporte Financiero en Excel")
    try:
        df = pd.read_csv("registro_impresiones.csv")
        ruta_excel = os.path.join(CARPETA_PRUEBAS, "Reporte_Prueba_Generado.xlsx")
        df.to_excel(ruta_excel, index=False, engine="openpyxl")
        print(f"   ✅ ÉXITO: Excel financiero generado correctamente en -> {ruta_excel}\n")
    except Exception as e:
        print(f"   ❌ ERROR generando Excel: {e}\n")

    print(f"🏁 PRUEBAS FINALIZADAS. Abre la carpeta '{CARPETA_PRUEBAS}' para inspeccionar los PDFs y el Excel.")

if __name__ == "__main__":
    asyncio.run(ejecutar_bateria_completa())