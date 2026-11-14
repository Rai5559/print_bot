import os
import uuid
import shutil
import time
from datetime import datetime, timedelta, time as dt_time
import pytz
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import ollama
from PIL import Image
from dotenv import load_dotenv
import math
import pymupdf as fitz
from PIL import Image, ImageChops, ImageStat, ImageOps, ImageEnhance
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
import aiohttp
import json
from docx2pdf import convert as convert_docx
import numpy as np
import re
import csv
import pandas as pd
import base64
from io import BytesIO
from playwright.async_api import async_playwright
import rectpack
import cv2

# ================= CONFIGURACIÓN =================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT")
BASE_DIR = "archivos_impresion"

ids_str = os.getenv("USUARIOS_AUTORIZADOS", "")
USUARIOS_AUTORIZADOS = [int(i.strip()) for i in ids_str.split(",") if i.strip()]

# Memoria temporal para agrupar archivos antes de la instrucción de texto
# Estructura: {chat_id: {"archivos": [ruta1, ruta2]}}
sesiones_activas = {}

# ================= FUNCIONES CORE =================

def crear_carpetas_orden(chat_id):
    """Crea la estructura de carpetas: fecha / uuid / originales | procesados"""
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    orden_id = str(uuid.uuid4())[:8] # UUID corto
    
    ruta_originales = os.path.join(BASE_DIR, fecha_hoy, orden_id, "originales")
    ruta_procesados = os.path.join(BASE_DIR, fecha_hoy, orden_id, "procesados")
    
    os.makedirs(ruta_originales, exist_ok=True)
    os.makedirs(ruta_procesados, exist_ok=True)
    
    return orden_id, ruta_originales, ruta_procesados

async def extraer_instrucciones_llm(texto_usuario, num_archivos):
    prompt_sistema = f"""
    Eres el cerebro de un centro de copiado. Convierte la solicitud a un JSON estricto.
    
    CONTEXTO VITAL: El usuario adjuntó {num_archivos} archivos/imágenes.
    
    CARRIL 1: DISEÑOS ASIMÉTRICOS Y LIBRES (HTML)
    - 'modo_html': true si piden posiciones ("arriba", "abajo"), diseños libres o auto-ajuste fluido.
    - 'codigo_html': Escribe el HTML/CSS. Usa {{img_0}}, {{img_1}} como src.
    
    CARRIL 2: MODO PLANILLA EXACTA
    - 'modo_planilla': true SOLO si piden medidas exactas (ej "5x5") o "infantil". 
    
    CARRIL 3: CUADRÍCULAS BÁSICAS
    - 'layout_n_up': Número de imágenes por hoja (ej "3 por página").
    
    CARRIL 4: MODO TETRIS / MÁXIMA EFICIENCIA
    - 'modo_tetris': true si piden "aprovechando el espacio", "como quepan" o "sin desperdiciar". 
    
    CARRIL 5: MODO ESCÁNER (AHORRO DE TINTA)
    - 'modo_escaner': true si el cliente pide "aclarar fondo", "modo documento", "modo escáner", "limpiar foto" o "quitar sombras".
    
    VALORES POR DEFECTO:
    {{
      "copias": 1,
      "layout_n_up": 1,
      "color": false,
      "doble_cara": false,
      "tamano_papel": "carta",
      "tipo_papel": "normal",
      "orientacion": "vertical",
      "sin_bordes": false,
      "tipo_documento": "normal",
      "escala_porcentaje": 100,
      "modo_planilla": false,
      "dimensiones_cm": null,
      "repeticiones": 1,
      "rango_paginas": "todos",
      "modo_html": false,
      "codigo_html": "",
      "forzar_rotacion": "ninguna",
      "modo_tetris": false,
      "modo_escaner": false
    }}
    """
    
    response = ollama.chat(
        model='llama3.1:8b',
        messages=[
            {'role': 'system', 'content': prompt_sistema},
            {'role': 'user', 'content': texto_usuario}
        ],
        format='json'
    )
    return json.loads(response['message']['content'])

def crear_lienzo(tamano="carta", orientacion="vertical"):
    """Genera el lienzo y lo acuesta si el usuario pide horizontal."""
    ancho, alto = 2550, 3300 # Carta
    if tamano.lower() == "oficio":
        ancho, alto = 2550, 4200
        
    if orientacion.lower() == "horizontal":
        ancho, alto = alto, ancho # Invierte las dimensiones
        
    return Image.new("RGB", (ancho, alto), "white")

def optimizar_orientacion(img, ancho_celda, alto_celda):
    """Rota la imagen 90 grados automáticamente si eso permite aprovechar más papel."""
    ratio_celda = ancho_celda / alto_celda
    ratio_img = img.width / img.height
    
    celda_es_horizontal = ratio_celda > 1
    img_es_horizontal = ratio_img > 1
    
    if celda_es_horizontal != img_es_horizontal:
        return img.rotate(90, expand=True)
    return img

def analizar_rango(rango_val, total_paginas):
    """Convierte casi cualquier locura que devuelva el LLM o el usuario en índices válidos."""
    if not rango_val or str(rango_val).lower() in ["todos", "todas", "todo", "null", "none", "[]", ""]:
        return None
    
    paginas_a_imprimir = set()
    
    # 1. Si el LLM devolvió una lista por error (ej. ["13-23", "45-50"])
    if isinstance(rango_val, list):
        rango_str = ",".join(str(x) for x in rango_val)
    else:
        rango_str = str(rango_val)
        
    # 2. Limpieza hardcore de lenguaje humano
    rango_limpio = rango_str.lower().replace(" y ", ",").replace(" e ", ",").replace("&", ",")
    rango_limpio = rango_limpio.replace(" al ", "-").replace(" a ", "-")
    
    # 3. Expresión regular: Destruir TODO lo que no sea un número, una coma o un guión
    rango_limpio = re.sub(r'[^\d,\-]', '', rango_limpio)
    
    partes = rango_limpio.split(",")
    for parte in partes:
        if "-" in parte:
            try:
                # Extraer los números, ignorando guiones vacíos
                nums = [int(n) for n in parte.split("-") if n]
                if len(nums) >= 2:
                    # Ordenar por si el LLM pone "23-13" por error
                    inicio, fin = min(nums[0], nums[1]), max(nums[0], nums[1])
                    for p in range(inicio-1, fin):
                        if 0 <= p < total_paginas:
                            paginas_a_imprimir.add(p)
            except: pass
        elif parte:
            try:
                p = int(parte) - 1
                if 0 <= p < total_paginas:
                    paginas_a_imprimir.add(p)
            except: pass
            
    return list(paginas_a_imprimir) if paginas_a_imprimir else None

def guardar_registro_csv(orden_id, config, costos):
    """Guarda silenciosamente la orden en una base de datos local CSV."""
    archivo_csv = "registro_impresiones.csv"
    existe = os.path.isfile(archivo_csv)
    
    with open(archivo_csv, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not existe:
            # Crear cabeceras si el archivo es nuevo
            writer.writerow(["Fecha", "Hora", "Orden_ID", "Tamano", "Tipo_Papel", 
                             "Copias", "Hojas_Fisicas", "Pags_BN", "Pags_Color", "Pags_Foto",
                             "Costo_Total", "Venta_Total", "Ganancia"])
        
        fecha = datetime.now().strftime("%Y-%m-%d")
        hora = datetime.now().strftime("%H:%M:%S")
        
        writer.writerow([
            fecha, hora, orden_id, 
            config.get("tamano_papel", "carta").upper(), 
            config.get("tipo_papel", "normal").upper(),
            config.get("copias", 1), 
            costos["hojas_fisicas_a_usar"],
            costos["resumen_tipos"]["texto_bn"], 
            costos["resumen_tipos"]["texto_color"], 
            costos["resumen_tipos"]["imagen_full"],
            costos["costo_interno_mxn"], 
            costos["precio_venta_sugerido"], 
            costos["ganancia_estimada"]
        ])

def mejorar_contraste_ine(img):
    """Mejora automática para credenciales: Mantiene el color pero limpia fondos grises."""
    img = img.convert("RGB")
    # Autocontraste: hace los blancos más blancos y los negros más negros
    img = ImageOps.autocontrast(img, cutoff=1)
    # Subir el brillo un 20% para fulminar el fondo grisáceo clásico de los celulares
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.2)
    return img

def limpiar_documento_opencv(img):
    """Convierte fotos oscuras con sombras en documentos escaneados puros (B/N)."""
    # 1. Convertir imagen de Pillow a matriz matemática de OpenCV
    img_cv = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    
    # 2. Pasar a escala de grises
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    
    # 3. UMBRAL ADAPTATIVO (Magia contra las sombras de manos y celulares)
    # En lugar de un filtro global, analiza regiones de 21x21 píxeles. 
    # Borra las sombras de gradiente pero mantiene la tinta negra intacta.
    thresh = cv2.adaptiveThreshold(
        gray, 255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 
        21, 15
    )
    
    # Convertir de regreso al formato Pillow
    return Image.fromarray(thresh).convert("RGB")

async def unificar_y_procesar_a_pdf(lista_archivos, ruta_procesados, config_json):
    ruta_salida = os.path.join(ruta_procesados, "documento_final.pdf")
    layout_n = config_json.get("layout_n_up", 1)
    tamano_papel = config_json.get("tamano_papel", "carta")
    orientacion = config_json.get("orientacion", "vertical")
    
    tipo_doc = config_json.get("tipo_documento", "normal").lower()
    escala = config_json.get("escala_porcentaje", 100) / 100.0

    forzar_rotacion = config_json.get("forzar_rotacion", "ninguna")

    todas_las_imagenes = []
    
    for archivo in lista_archivos:
        ext = archivo.lower().split('.')[-1]
        if ext in ['docx', 'doc']:
            ruta_temp_pdf = archivo.replace(f".{ext}", ".pdf")
            convert_docx(archivo, ruta_temp_pdf)
            archivo_a_procesar = ruta_temp_pdf
            es_pdf = True
        elif ext == 'pdf':
            archivo_a_procesar = archivo
            es_pdf = True
        else:
            archivo_a_procesar = archivo
            es_pdf = False

        if es_pdf:
            rango_str = config_json.get("rango_paginas", "todos")
            doc = fitz.open(archivo_a_procesar)
            
            # Decodificamos qué páginas quiere el cliente realmente
            paginas_validas = analizar_rango(rango_str, len(doc))
            
            for i in range(len(doc)):
                # Si hay un filtro activo y esta página NO está en la lista, la saltamos (Ahorro masivo de RAM)
                if paginas_validas is not None and i not in paginas_validas:
                    continue
                    
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(4.16, 4.16)) 
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                todas_las_imagenes.append(img)
            doc.close()
        else:
            todas_las_imagenes.append(Image.open(archivo_a_procesar).convert("RGB"))

    # =========================================================
    # PRE-PROCESAMIENTO: ROTACIÓN FORZADA
    # =========================================================
    for idx, img in enumerate(todas_las_imagenes):
        if forzar_rotacion == "vertical" and img.width > img.height:
            todas_las_imagenes[idx] = img.rotate(90, expand=True)
        elif forzar_rotacion == "horizontal" and img.height > img.width:
            todas_las_imagenes[idx] = img.rotate(90, expand=True)

    # =========================================================
    # MEJORA VISUAL AUTOMÁTICA (MODO ESCÁNER / INE)
    # =========================================================
    modo_escaner = config_json.get("modo_escaner", False)
    
    for idx, img in enumerate(todas_las_imagenes):
        if tipo_doc == "ine":
            # Si es INE, aplicamos limpieza ligera para no perder la foto/color de la persona
            todas_las_imagenes[idx] = mejorar_contraste_ine(img)
        elif modo_escaner:
            # Si piden modo escáner para recibos o actas, aplicamos B/N agresivo anti-sombras
            todas_las_imagenes[idx] = limpiar_documento_opencv(img)

    # =========================================================
    # CARRIL HTML / DISEÑOS ASIMÉTRICOS (PLAYWRIGHT BLINDADO)
    # =========================================================
    if config_json.get("modo_html", False) and config_json.get("codigo_html"):
        codigo_base = config_json.get("codigo_html", "")
        
        # 1. Sanitización básica: Eliminar cualquier etiqueta <script> por si el LLM alucina
        codigo_base = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', codigo_base, flags=re.IGNORECASE)
        
        # 2. Reemplazar las variables {img_0}, {img_1} por los datos base64 reales
        for idx, img in enumerate(todas_las_imagenes):
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            b64_uri = f"data:image/png;base64,{img_str}"
            codigo_base = codigo_base.replace(f"{{img_{idx}}}", b64_uri)
            
        # 3. Mapear tamaño y orientación real para CSS y Playwright
        formato_pw = "Legal" if tamano_papel.lower() == "oficio" else "Letter"
        es_horizontal = (orientacion.lower() == "horizontal")
        size_css = f"{formato_pw.lower()} {'landscape' if es_horizontal else 'portrait'}"
            
        html_final = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                @page {{ size: {size_css}; margin: 0; }}
                body {{ margin: 0; padding: 0; box-sizing: border-box; width: 100vw; height: 100vh; overflow: hidden; }}
            </style>
        </head>
        <body>{codigo_base}</body>
        </html>
        """
        
        # 4. Lanzar Chrome en modo fantasma con bloqueo de red y timeout estricto
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # CORTAFUEGOS: Bloquear cualquier petición externa (solo permitir imágenes base64 "data:" o "about:blank")
            await page.route(
                "**/*", 
                lambda route: route.continue_() if route.request.url.startswith(("data:", "about:")) else route.abort()
            )
            
            # Timeout estricto de 5 segundos para evitar cuelgues
            await page.set_content(html_final, timeout=5000, wait_until="domcontentloaded")
            
            await page.pdf(
                path=ruta_salida, 
                format=formato_pw, 
                landscape=es_horizontal,
                print_background=True
            )
            await browser.close()
            
        return ruta_salida

    # =========================================================
    # MODO TETRIS MATEMÁTICO (BIN PACKING)
    # =========================================================
    if config_json.get("modo_tetris", False):
        
        espaciado = 20 # Espacio para cortes
        margen_seguro = 50 # Margen perimetral
        
        hoja_prueba = crear_lienzo(tamano_papel, orientacion)
        ancho_util = hoja_prueba.width - (margen_seguro * 2)
        alto_util = hoja_prueba.height - (margen_seguro * 2)
        
        # rotation=True permite al algoritmo girar las fotos para encontrar huecos
        packer = rectpack.newPacker(rotation=True)
        
        # 1. Alimentar al algoritmo con el tamaño original de cada imagen
        for idx, img in enumerate(todas_las_imagenes):
            packer.add_rect(img.width + espaciado, img.height + espaciado, rid=idx)
            
        # 2. Agregar hojas en blanco infinitas (el algoritmo usará solo las necesarias)
        for _ in range(len(todas_las_imagenes)):
            packer.add_bin(ancho_util, alto_util)
            
        # 3. Calcular el empaquetado perfecto
        packer.pack()
        
        paginas_pdf = []
        
        # 4. Dibujar los resultados
        for bin in packer:
            hoja = crear_lienzo(tamano_papel, orientacion)
            for rect in bin:
                idx = rect.rid
                img = todas_las_imagenes[idx]
                
                # Si el algoritmo decidió que la imagen encajaba mejor rotada, la giramos físicamente
                if rect.width != (img.width + espaciado):
                    img = img.rotate(90, expand=True)
                    
                x_pos = margen_seguro + rect.x
                y_pos = margen_seguro + rect.y
                
                hoja.paste(img, (x_pos, y_pos))
                
            paginas_pdf.append(hoja)
            
        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
            
        return ruta_salida

    # =========================================================
    # MODO ESPECIAL: COPIA DE INE / IDENTIFICACIONES
    # =========================================================
    if tipo_doc == "ine" and len(todas_las_imagenes) <= 2:
        hoja = crear_lienzo(tamano_papel, orientacion)
        ancho_ine = int(1015 * escala)
        alto_ine = int(638 * escala)
        
        for idx, img in enumerate(todas_las_imagenes):
            # MAGIA: Si el cliente mandó la foto vertical, la acostamos (90 grados)
            if img.height > img.width:
                img = img.rotate(90, expand=True)
                
            img_opt = ImageOps.pad(img, (ancho_ine, alto_ine), method=Image.Resampling.LANCZOS, color="white")
            x_offset = (hoja.width - img_opt.width) // 2
            y_base = (hoja.height // 2) * idx 
            y_offset = y_base + ((hoja.height // 2) - img_opt.height) // 2
            hoja.paste(img_opt, (x_offset, y_offset))
            
        hoja.save(ruta_salida, resolution=300.0)
        return ruta_salida

    # =========================================================
    # 2. MODO PLANILLA UNIVERSAL Y TAMAÑOS EXACTOS (ANCLAJE TOP-LEFT)
    # =========================================================
    modo_planilla = config_json.get("modo_planilla", False)
    dimensiones_cm = config_json.get("dimensiones_cm")
    repeticiones = config_json.get("repeticiones", 1)

    if modo_planilla or dimensiones_cm:
        paginas_pdf = []
        DPI_CM = 118.11 # 300 Píxeles / 2.54 cm
        
        if dimensiones_cm and isinstance(dimensiones_cm, list) and len(dimensiones_cm) == 2:
            ancho_px = int(dimensiones_cm[0] * DPI_CM)
            alto_px = int(dimensiones_cm[1] * DPI_CM)
        else:
            ancho_px = int(10 * DPI_CM)
            alto_px = int(15 * DPI_CM)

        espaciado = 20 # Píxeles de separación para tijeras
        margen_seguro = 100 # Margen superior e izquierdo (aprox 8.5 mm)
        
        hoja_prueba = crear_lienzo(tamano_papel, orientacion)
        
        # Calcular capacidad tomando en cuenta que ahora partimos desde una esquina
        espacio_util_x = hoja_prueba.width - (margen_seguro * 2)
        espacio_util_y = hoja_prueba.height - (margen_seguro * 2)
        
        cols_posibles = max(1, espacio_util_x // (ancho_px + espaciado))
        filas_posibles = max(1, espacio_util_y // (alto_px + espaciado))
        capacidad_hoja = cols_posibles * filas_posibles

        # Preparar la lista de impresión con relleno inteligente (pad)
        lista_a_imprimir = []
        if repeticiones == 0:
            capacidad_por_img = max(1, capacidad_hoja // len(todas_las_imagenes))
            for img in todas_las_imagenes:
                img_rec = ImageOps.pad(img, (ancho_px, alto_px), method=Image.Resampling.LANCZOS, color="white")
                lista_a_imprimir.extend([img_rec] * capacidad_por_img)
        else:
            for img in todas_las_imagenes:
                img_rec = ImageOps.pad(img, (ancho_px, alto_px), method=Image.Resampling.LANCZOS, color="white")
                lista_a_imprimir.extend([img_rec] * repeticiones)

        # Acomodar en la cuadrícula (Anclada arriba a la izquierda)
        hoja_actual = crear_lienzo(tamano_papel, orientacion)
        dibujadas_en_hoja = 0

        for i, img_lista in enumerate(lista_a_imprimir):
            col = dibujadas_en_hoja % cols_posibles
            fila = dibujadas_en_hoja // cols_posibles
            
            # Aquí ocurre la magia del ahorro de papel:
            x_pos = margen_seguro + (col * (ancho_px + espaciado))
            y_pos = margen_seguro + (fila * (alto_px + espaciado))
            
            hoja_actual.paste(img_lista, (x_pos, y_pos))
            dibujadas_en_hoja += 1

            if dibujadas_en_hoja >= capacidad_hoja or i == len(lista_a_imprimir) - 1:
                paginas_pdf.append(hoja_actual)
                if i != len(lista_a_imprimir) - 1:
                    hoja_actual = crear_lienzo(tamano_papel, orientacion)
                    dibujadas_en_hoja = 0

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # =========================================================
    # CÁLCULO DE CUADRÍCULA INTELIGENTE
    # =========================================================
    img_ejemplo = todas_las_imagenes[0] if todas_las_imagenes else None
    es_img_horizontal = img_ejemplo.width > img_ejemplo.height if img_ejemplo else True
    
    columnas, filas = 1, 1
    if layout_n == 2:
        if orientacion == "vertical":
            columnas, filas = (1, 2) if es_img_horizontal else (2, 1)
        else:
            columnas, filas = (2, 1) if es_img_horizontal else (1, 2)
    elif layout_n > 2:
        # Fórmula maestra: Para 3 o 4 (2x2), para 5 o 6 (2x3), para 7 u 8 (2x4)...
        columnas = 2
        filas = math.ceil(layout_n / 2)

    # =========================================================
    # EMPAQUETADO COMPACTO (CLUSTERING POR ESCALA)
    # =========================================================
    paginas_pdf = []
    for i in range(0, len(todas_las_imagenes), layout_n):
        lote = todas_las_imagenes[i:i + layout_n]
        hoja = crear_lienzo(tamano_papel, orientacion)
        
        # Tamaño base de la celda si ocupara toda la hoja
        ancho_base = hoja.width // columnas
        alto_base = hoja.height // filas
        
        # Tamaño real de la celda reducida
        ancho_celda_real = int(ancho_base * escala)
        alto_celda_real = int(alto_base * escala)
        
        # Agruparlas arriba al centro si hay reducción
        if escala < 1.0:
            grid_x_start = (hoja.width - (ancho_celda_real * columnas)) // 2
            grid_y_start = 150 # Margen superior para que queden pegadas arriba
        else:
            grid_x_start = 0
            grid_y_start = 0
        
        for idx, img in enumerate(lote):
            col = idx % columnas
            fila = idx // columnas
            
            # Punto de anclaje de esta celda en el empaquetado
            x_base = grid_x_start + (col * ancho_celda_real)
            y_base = grid_y_start + (fila * alto_celda_real)
            
            # Se optimiza la imagen para encajar perfectamente en su nueva celda reducida
            img_optimizada = optimizar_orientacion(img, ancho_celda_real, alto_celda_real)
            
            if config_json.get("sin_bordes", False):
                img_optimizada = ImageOps.fit(
                    img_optimizada, (ancho_celda_real, alto_celda_real), 
                    method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
                )
            else:
                margen = 15 if escala >= 1.0 else 0 
                img_optimizada = ImageOps.contain(
                    img_optimizada, (ancho_celda_real - margen*2, alto_celda_real - margen*2), 
                    method=Image.Resampling.LANCZOS
                )
            
            # Centrar dentro de la pequeña celda empaquetada
            x_offset = x_base + (ancho_celda_real - img_optimizada.width) // 2
            y_offset = y_base + (alto_celda_real - img_optimizada.height) // 2
            
            hoja.paste(img_optimizada, (x_offset, y_offset))
            
        paginas_pdf.append(hoja)
        
    if paginas_pdf:
        paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        
    return ruta_salida

def analizar_cobertura_pagina(page):
    """
    Renderiza la página y usa Numpy para calcular el % exacto de tinta a color y B/N.
    """
    # Renderizamos a 72 DPI (suficiente para análisis de cobertura y ultra rápido)
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csRGB)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    # Convertimos la imagen a una matriz matemática de píxeles
    img_array = np.array(img)
    
    # 1. Detectar píxeles "blancos" (el papel) - RGB por encima de 240
    mascara_blanca = np.all(img_array > 240, axis=-1)
    
    # 2. Calcular la diferencia entre el canal más fuerte y el más débil
    max_c = np.max(img_array, axis=-1).astype(int)
    min_c = np.min(img_array, axis=-1).astype(int)
    diferencia = max_c - min_c
    
    # 3. Clasificar los píxeles (ignorando el fondo blanco)
    # Color: Hay variación fuerte entre RGB (ej. rojo es R:255, G:0, B:0)
    mascara_color = (diferencia > 15) & (~mascara_blanca)
    # B/N: Poca variación entre RGB (ej. gris es R:100, G:100, B:100)
    mascara_bn = (diferencia <= 15) & (~mascara_blanca)
    
    total_pixeles = img_array.shape[0] * img_array.shape[1]
    
    # Porcentajes de cobertura (0.0 a 1.0)
    cobertura_color = np.sum(mascara_color) / total_pixeles
    cobertura_bn = np.sum(mascara_bn) / total_pixeles
    
    return cobertura_color, cobertura_bn

def calcular_costo_gx7110(pdf_path, config_json):
    """Calcula precios dinámicos basándose en el consumo exacto de tinta (cobertura)."""
    doc = fitz.open(pdf_path)
    num_paginas = len(doc)
    
    copias = config_json.get("copias", 1)
    doble_cara = config_json.get("doble_cara", False)
    forzar_bn = (config_json.get("color") is False)
    es_fotografico = config_json.get("tipo_papel") == "fotografico"
    
    costo_tinta_total = 0.0
    precio_venta_total = 0.0
    
    # Estadísticas para mostrarle a tu padre en Telegram
    resumen = {"texto_bn": 0, "texto_color": 0, "imagen_full": 0}
    
    # Costos base por HOJA COMPLETA (Asumiendo 100% de cobertura de tinta en la Maxify)
    costo_100pct_color = 1.00 if not es_fotografico else 1.50
    costo_100pct_bn = 0.60
    
    for i in range(num_paginas):
        cob_color, cob_bn = analizar_cobertura_pagina(doc[i])
        
        if forzar_bn:
            cob_bn = cob_bn + cob_color
            cob_color = 0.0
            
        # Gasto exacto de tinta de esta página basado en su porcentaje de mancha
        gasto_tinta_pag = (cob_color * costo_100pct_color) + (cob_bn * costo_100pct_bn)
        costo_tinta_total += gasto_tinta_pag
        
        # PRECIOS DE VENTA DINÁMICOS POR PÁGINA SEGÚN COBERTURA
        if es_fotografico:
            precio_pag = 15.00 # Foto siempre se cobra premium
            resumen["imagen_full"] += 1
        else:
            if cob_color > 0.15:
                # Más del 15% de color (Fotos rellenas, posters sin bordes)
                precio_pag = 6.00
                resumen["imagen_full"] += 1
            elif cob_color > 0.01:
                # Entre 1% y 15% (Documento de texto con títulos de color o gráficas)
                precio_pag = 3.00
                resumen["texto_color"] += 1
            else:
                # Puro B/N o con color imperceptible
                precio_pag = 1.50
                resumen["texto_bn"] += 1
                
        precio_venta_total += precio_pag
        
    doc.close()
    
    # Multiplicar por juegos (copias)
    costo_tinta_total *= copias
    precio_venta_total *= copias
    
    # Calcular Papel
    hojas_fisicas_por_copia = math.ceil(num_paginas / 2) if doble_cara else num_paginas
    total_hojas_papel = hojas_fisicas_por_copia * copias
    costo_hoja = 3.00 if es_fotografico else 0.30
    costo_interno_papel = total_hojas_papel * costo_hoja
    
    costo_interno_total = costo_interno_papel + costo_tinta_total
    ganancia = precio_venta_total - costo_interno_total
    
    # Multiplicar el resumen por las copias para el reporte
    resumen = {k: v * copias for k, v in resumen.items()}
    
    return {
        "paginas_totales": num_paginas * copias,
        "resumen_tipos": resumen,
        "hojas_fisicas_a_usar": total_hojas_papel,
        "costo_interno_mxn": round(costo_interno_total, 2),
        "precio_venta_sugerido": round(precio_venta_total, 2),
        "ganancia_estimada": round(ganancia, 2)
    }

# ================= HANDLERS DE TELEGRAM =================

async def enviar_a_fastapi(pdf_path, config_json):
    """Envía el PDF final y la configuración a la PC de la tienda vía WireGuard."""
    # CAMBIA ESTO por la IP que tenga la PC de la tienda en tu túnel WireGuard
    url_tienda = "http://10.5.5.4:8000/imprimir" 
    
    try:
        async with aiohttp.ClientSession() as session:
            with open(pdf_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('archivo', f, filename=os.path.basename(pdf_path))
                data.add_field('config', json.dumps(config_json))
                
                async with session.post(url_tienda, data=data) as response:
                    if response.status == 200:
                        return True, "Enviado con éxito."
                    else:
                        return False, f"Error del servidor de la tienda: {response.status}"
    except Exception as e:
        return False, f"No se pudo conectar con la tienda. ¿Está encendida la PC o el túnel? Error: {str(e)}"

async def generar_y_enviar_reporte(update: Update, texto: str):
    archivo_csv = "registro_impresiones.csv"
    if not os.path.exists(archivo_csv):
        await update.message.reply_text("⚠️ Aún no hay trabajos registrados en el sistema.")
        return
        
    # Leer la base de datos
    df = pd.read_csv(archivo_csv)
    df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
    hoy = datetime.now().date()
    texto = texto.lower()
    
    # Filtros de Tiempo Inteligentes
    if "hoy" in texto or "diario" in texto:
        df_filtro = df[df['Fecha'] == hoy]
        periodo = "Hoy"
    elif "semana" in texto:
        inicio_semana = hoy - pd.Timedelta(days=hoy.weekday())
        df_filtro = df[df['Fecha'] >= inicio_semana]
        periodo = "Esta Semana"
    elif "mes" in texto:
        df_filtro = df[pd.to_datetime(df['Fecha']).dt.month == hoy.month]
        periodo = "Este Mes"
    else:
        df_filtro = df # Histórico completo
        periodo = "Histórico Completo"
        
    if df_filtro.empty:
        await update.message.reply_text(f"📊 No hay impresiones registradas para el periodo: **{periodo}**.", parse_mode='Markdown')
        return

    # Cálculos Matemáticos
    ventas = df_filtro['Venta_Total'].sum()
    costos = df_filtro['Costo_Total'].sum()
    ganancia = df_filtro['Ganancia'].sum()
    hojas = df_filtro['Hojas_Fisicas'].sum()
    fotos = df_filtro['Pags_Foto'].sum()
    bn = df_filtro['Pags_BN'].sum()
    color = df_filtro['Pags_Color'].sum()

    resumen = f"📊 **REPORTE FINANCIERO: {periodo.upper()}**\n\n"
    resumen += f"💰 **Ingresos Brutos:** ${ventas:.2f} MXN\n"
    resumen += f"📉 **Gasto en Insumos:** ${costos:.2f} MXN\n"
    resumen += f"✅ **GANANCIA NETA:** ${ganancia:.2f} MXN\n\n"
    resumen += f"📦 **Consumo Físico:**\n"
    resumen += f"- Hojas utilizadas: {hojas}\n"
    resumen += f"- Impresiones B/N: {bn}\n"
    resumen += f"- Impresiones Color: {color}\n"
    resumen += f"- Fotografías Premium: {fotos}\n"

    # Generar Excel al vuelo
    nombre_excel = f"Reporte_{periodo.replace(' ', '_')}.xlsx"
    df_filtro.to_excel(nombre_excel, index=False, engine='openpyxl')
    
    # Enviar por Telegram
    with open(nombre_excel, 'rb') as doc:
        await update.message.reply_document(
            document=doc,
            filename=nombre_excel,
            caption=resumen,
            parse_mode='Markdown'
        )
        
    os.remove(nombre_excel) # Borramos el Excel temporal para no saturar el disco


async def tarea_mantenimiento_y_limpieza(context: ContextTypes.DEFAULT_TYPE = None):
    """Borra temporales de 24h y carpetas de más de 15 días."""
    print("🧹 Iniciando limpieza automática de disco...")
    ahora = time.time()

    # 1. Limpiar temp_uploads (> 24 horas)
    temp_dir = "temp_uploads"
    if os.path.exists(temp_dir):
        for archivo in os.listdir(temp_dir):
            ruta = os.path.join(temp_dir, archivo)
            if os.path.isfile(ruta):
                if (ahora - os.path.getmtime(ruta)) > (24 * 3600):
                    os.remove(ruta)
                    print(f"🗑️ Eliminado temporal caducado: {archivo}")

    # 2. Limpiar archivos_impresion (> 15 días)
    base_dir = "archivos_impresion" # Carpeta base que configuraste
    if os.path.exists(base_dir):
        hace_15_dias = datetime.now() - timedelta(days=15)
        for carpeta_fecha in os.listdir(base_dir):
            ruta_carpeta = os.path.join(base_dir, carpeta_fecha)
            if os.path.isdir(ruta_carpeta):
                try:
                    # Aprovechamos que nombras las carpetas con la fecha (ej. "2026-11-13")
                    fecha_carpeta = datetime.strptime(carpeta_fecha, "%Y-%m-%d")
                    if fecha_carpeta < hace_15_dias:
                        shutil.rmtree(ruta_carpeta)
                        print(f"🗑️ Eliminado histórico caducado: {carpeta_fecha}")
                except ValueError:
                    pass

async def enviar_corte_automatico(context: ContextTypes.DEFAULT_TYPE):
    """Genera y envía el Excel del día sin que nadie lo pida."""
    print("📊 Ejecutando corte de caja automático de las 10:05 PM...")
    archivo_csv = "registro_impresiones.csv"
    if not os.path.exists(archivo_csv):
        return

    # Leer datos
    import pandas as pd
    df = pd.read_csv(archivo_csv)
    df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
    hoy = datetime.now().date()
    
    df_hoy = df[df['Fecha'] == hoy]
    
    # Asegúrate de tener declarada tu variable USUARIOS_AUTORIZADOS arriba en tu código
    for admin_id in USUARIOS_AUTORIZADOS:
        try:
            if df_hoy.empty:
                await context.bot.send_message(chat_id=admin_id, text="🌙 **CORTE AUTOMÁTICO:**\nHoy no hubo impresiones.")
                continue

            ventas = df_hoy['Venta_Total'].sum()
            costos = df_hoy['Costo_Total'].sum()
            ganancia = df_hoy['Ganancia'].sum()

            resumen = f"🌙 **CORTE DE CAJA AUTOMÁTICO: {hoy}**\n\n"
            resumen += f"💰 **Ingresos de hoy:** ${ventas:.2f} MXN\n"
            resumen += f"📉 **Gasto Insumos:** ${costos:.2f} MXN\n"
            resumen += f"✅ **GANANCIA:** ${ganancia:.2f} MXN\n"

            nombre_excel = f"Corte_Diario_{hoy}.xlsx"
            df_hoy.to_excel(nombre_excel, index=False, engine='openpyxl')
            
            with open(nombre_excel, 'rb') as doc:
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=doc,
                    filename=nombre_excel,
                    caption=resumen,
                    parse_mode='Markdown'
                )
        except Exception as e:
            print(f"Error enviando reporte automático a {admin_id}: {e}")
            
    if os.path.exists("Corte_Diario_" + str(hoy) + ".xlsx"):
        os.remove("Corte_Diario_" + str(hoy) + ".xlsx")

async def recibir_archivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    if USUARIOS_AUTORIZADOS and user_id not in USUARIOS_AUTORIZADOS:
        await update.message.reply_text("⛔ No tienes autorización para usar este servicio de impresión.")
        return
    
    # Inicializar memoria para este usuario si no existe
    if chat_id not in sesiones_activas:
        sesiones_activas[chat_id] = {"archivos_temporales": []}
    
    # Identificar si es documento o foto
    archivo_tg = None
    extension = ""
    if update.message.document:
        archivo_tg = await update.message.document.get_file()
        extension = os.path.splitext(update.message.document.file_name)[1]
    elif update.message.photo:
        archivo_tg = await update.message.photo[-1].get_file() # Mayor resolución
        extension = ".jpg"
        
    # Guardar en una carpeta temporal global (se moverán al crear la orden)
    tmp_dir = "temp_uploads"
    os.makedirs(tmp_dir, exist_ok=True)
    ruta_tmp = os.path.join(tmp_dir, f"{uuid.uuid4()}{extension}")
    
    await archivo_tg.download_to_drive(ruta_tmp)
    sesiones_activas[chat_id]["archivos_temporales"].append(ruta_tmp)
    
    await update.message.reply_text(f"📁 Archivo recibido. Llevas {len(sesiones_activas[chat_id]['archivos_temporales'])} archivo(s). Manda más, o envíame las instrucciones por texto para procesar la orden.")

async def procesar_instruccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    texto = update.message.text

    user_id = update.effective_user.id
    if USUARIOS_AUTORIZADOS and user_id not in USUARIOS_AUTORIZADOS:
        await update.message.reply_text("⛔ No tienes autorización para usar este servicio de impresión.")
        return
    
    if chat_id not in sesiones_activas or not sesiones_activas[chat_id]["archivos_temporales"]:
        if "reporte" in texto.lower():
            await generar_y_enviar_reporte(update, texto)
            return
        await update.message.reply_text("⚠️ No tengo archivos pendientes. Manda los documentos primero.")
        return
        
    mensaje_estado = await update.message.reply_text("🧠 Analizando instrucciones y generando orden...")
    
    try:
        cantidad_archivos = len(sesiones_activas[chat_id]["archivos_temporales"])
        config_impresion = await extraer_instrucciones_llm(texto, cantidad_archivos)
        
        # === FILTRO DE LIMPIEZA Y NORMALIZACIÓN (DOBLE VALIDACIÓN) ===
        texto_limpio = texto.lower() # Lo que el usuario escribió textualmente
        # En tu bloque de FILTRO DE LIMPIEZA Y NORMALIZACIÓN:
        if "200%" in texto_limpio or "al 200" in texto_limpio:
            config_impresion["escala_porcentaje"] = 200
        elif "50%" in texto_limpio or "mitad" in texto_limpio:
            config_impresion["escala_porcentaje"] = 50

        # Blindaje para Plantillas y Tamaños Exactos
        if "infantil" in texto_limpio:
            config_impresion["modo_planilla"] = True
            config_impresion["dimensiones_cm"] = [2.5, 3.0]
        elif "pasaporte" in texto_limpio:
            config_impresion["modo_planilla"] = True
            config_impresion["dimensiones_cm"] = [3.5, 4.5]
            
        if "llena la hoja" in texto_limpio or "toda la hoja" in texto_limpio or "planilla" in texto_limpio:
            config_impresion["modo_planilla"] = True
            if "repeticiones" not in config_impresion or config_impresion["repeticiones"] == 1:
                config_impresion["repeticiones"] = 0 # 0 activa el llenado matemático automático
        
        # 1. Limpiar Tipo de Papel (Revisa el JSON del LLM y también tu texto crudo)
        tipo_crudo = str(config_impresion.get("tipo_papel", "")).lower()
        if "foto" in tipo_crudo or "glossy" in tipo_crudo or "foto" in texto_limpio:
            config_impresion["tipo_papel"] = "fotografico"
        else:
            config_impresion["tipo_papel"] = "normal"
            
        # 2. Limpiar Tamaño de Papel
        tamano_crudo = str(config_impresion.get("tamano_papel", "")).lower()
        if "oficio" in tamano_crudo or "legal" in tamano_crudo or "oficio" in texto_limpio:
            config_impresion["tamano_papel"] = "oficio"
        else:
            config_impresion["tamano_papel"] = "carta"
            
        # 3. Forzar Sin Bordes y Color si el LLM lo olvidó
        if "sin borde" in texto_limpio:
            config_impresion["sin_bordes"] = True
        if "color" in texto_limpio:
            config_impresion["color"] = True

        # === CANDADO ESTRICTO DE RANGO DE PÁGINAS ===
        rango_actual = config_impresion.get("rango_paginas", "todos")
        if rango_actual in ["todos", "todas", None, "", "null"]:
            # Si el LLM falló por completo, buscamos nosotros el patrón numérico (ej. 13-23) en el texto
            rangos_hallados = re.findall(r'\d+\s*-\s*\d+', texto_limpio)
            if rangos_hallados:
                config_impresion["rango_paginas"] = ",".join(rangos_hallados)
        # ===================================================
            
        # === CANDADO ESTRICTO PARA DOBLE CARA ===
        # Lista de frases inequívocas que un cliente usa para doble cara
        frases_duplex = ["doble cara", "ambos lados", "frente y vuelta", "dos caras", "frente y reverso"]
        
        if any(frase in texto_limpio for frase in frases_duplex):
            config_impresion["doble_cara"] = True
        else:
            # Si no dijo ninguna de esas frases, apagamos el doble cara forzosamente
            # para evitar que el LLM confunda "imprime los dos archivos" con "doble cara"
            config_impresion["doble_cara"] = False
        # ===============================================
            
        # 4. Asegurar valores básicos
        config_impresion["copias"] = config_impresion.get("copias") or 1
        config_impresion["layout_n_up"] = config_impresion.get("layout_n_up") or 1
        # =============================================================
            
        # 2. Limpiar Tamaño de Papel
        tamano_crudo = str(config_impresion.get("tamano_papel", "")).lower()
        if "oficio" in tamano_crudo or "legal" in tamano_crudo:
            config_impresion["tamano_papel"] = "oficio"
        else:
            config_impresion["tamano_papel"] = "carta"
            
        # 3. Asegurar valores básicos si el LLM los omite
        config_impresion["copias"] = config_impresion.get("copias") or 1
        config_impresion["layout_n_up"] = config_impresion.get("layout_n_up") or 1
        # ==========================================
        
        # (A partir de aquí continúa tu código normal de unificar_y_procesar_a_pdf...)
    except Exception as e:
        await update.message.reply_text("❌ Hubo un error al entender las instrucciones.")
        return

    orden_id, ruta_originales, ruta_procesados = crear_carpetas_orden(chat_id)
    
    archivos_orden = []
    for arch_tmp in sesiones_activas[chat_id]["archivos_temporales"]:
        nombre_base = os.path.basename(arch_tmp)
        nueva_ruta = os.path.join(ruta_originales, nombre_base)
        os.rename(arch_tmp, nueva_ruta)
        archivos_orden.append(nueva_ruta)
        
    sesiones_activas.pop(chat_id)
    
    # Procesar y cotizar
    ruta_pdf_final = await unificar_y_procesar_a_pdf(archivos_orden, ruta_procesados, config_impresion)
    reporte_costos = calcular_costo_gx7110(ruta_pdf_final, config_impresion)

    with open(os.path.join(ruta_originales, "instruccion_cliente.txt"), "w", encoding="utf-8") as f:
        f.write(texto)
    
    # Construir el reporte
    # === CONSTRUIR EL REPORTE ===
    copias = config_impresion.get("copias", 1)
    es_doble_cara = "Doble Cara" if config_impresion.get("doble_cara") else "Normal"
    tamano = config_impresion.get("tamano_papel", "carta")
    tipo = config_impresion.get("tipo_papel", "normal")
    rango = config_impresion.get("rango_paginas", "todos")
    texto_rango = "Doc. Completo" if rango == "todos" else f"Págs: {rango}"
    
    res = f"✅ **Orden #{orden_id} Procesada**\n\n"
    res += f"⚙️ **Config:** {copias} Copias | {es_doble_cara} | {texto_rango}\n"
    res += f"📄 **Papel:** {tamano.upper()} | {tipo.upper()}\n\n"
    
    # NUEVO: Reporte detallado de Cobertura
    res += f"📊 **Análisis de Cobertura de Tinta:**\n"
    if reporte_costos['resumen_tipos']['texto_bn'] > 0:
        res += f"➖ Textos Blanco/Negro: {reporte_costos['resumen_tipos']['texto_bn']} págs\n"
    if reporte_costos['resumen_tipos']['texto_color'] > 0:
        res += f"➖ Textos con títulos/color: {reporte_costos['resumen_tipos']['texto_color']} págs\n"
    if reporte_costos['resumen_tipos']['imagen_full'] > 0:
        res += f"🖼️ Imágenes Full Color/Fotos: {reporte_costos['resumen_tipos']['imagen_full']} págs\n"
    
    res += f"\n- Hojas de papel a consumir: {reporte_costos['hojas_fisicas_a_usar']}\n\n"
    
    res += f"💰 **COBRO AL CLIENTE:** ${reporte_costos['precio_venta_sugerido']} MXN\n"
    res += f"*(Costo int: ${reporte_costos['costo_interno_mxn']} | Ganancia: ${reporte_costos['ganancia_estimada']})*\n\n"

    # Guardar en memoria para cuando presionen el botón
    context.user_data['ultima_orden'] = {
        'orden_id': orden_id,
        'pdf_path': ruta_pdf_final,
        'config': config_impresion,
        'costos': reporte_costos
    }
    
    await mensaje_estado.delete() 
    
    # LÓGICA DE BANDEJAS CLARA PARA EL USUARIO
    es_foto = config_impresion.get("tipo_papel") == "fotografico"
    es_oficio = config_impresion.get("tamano_papel") == "oficio"
    
    mensaje_accion = ""
    if es_foto or es_oficio:
        # Detectar qué tipo de papel especial es para el mensaje
        razon = []
        if es_oficio: razon.append("OFICIO")
        if es_foto: razon.append("FOTOGRÁFICO")
        
        mensaje_accion += f"⚠️ **ATENCIÓN:** Se requiere papel {' y '.join(razon)}.\n"
        mensaje_accion += "👉 Colócalo en la **BANDEJA POSTERIOR** (Rear Tray).\n\n"
    else:
        # Es bond tamaño carta. Dar tranquilidad de que es automático.
        mensaje_accion += "✅ **Papel Carta Normal.**\n"
        mensaje_accion += "👉 Se tomará automáticamente del **CASSETTE 1**.\n\n"
        
    mensaje_accion += "¿Todo correcto para imprimir?"
    
    # 2. Botones de confirmación y cancelación (AQUÍ ESTÁ LA VARIABLE FALTANTE)
    keyboard = [
        [InlineKeyboardButton("✅ Automático (Confirmar)", callback_data="print_auto")],
        [
            InlineKeyboardButton("📥 Cassette 1", callback_data="print_cas1"),
            InlineKeyboardButton("📥 Cassette 2", callback_data="print_cas2")
        ],
        [InlineKeyboardButton("📄 Bandeja Posterior", callback_data="print_rear")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # === ENVIAR RESUMEN DE COSTOS ===
    await update.message.reply_text(res, parse_mode='Markdown')
    
    # === ENVIAR VISTA PREVIA DEL PDF ===
    with open(ruta_pdf_final, 'rb') as pdf_file:
        await update.message.reply_document(
            document=pdf_file,
            filename=f"VistaPrevia_{orden_id}.pdf",
            caption="👀 **VISTA PREVIA DEL DOCUMENTO FINAL**\n(Abre el archivo para revisarlo con el cliente antes de imprimir)",
            parse_mode='Markdown',
            read_timeout=60, # Increased timeout to 60 seconds
            write_timeout=60,
            connect_timeout=60
        )
        
    # === ENVIAR BOTONES DE ACCIÓN ===
    await update.message.reply_text(mensaje_accion, parse_mode='Markdown', reply_markup=reply_markup)

async def boton_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 

    user_id = update.effective_user.id
    if USUARIOS_AUTORIZADOS and user_id not in USUARIOS_AUTORIZADOS:
        await update.message.reply_text("⛔ No tienes autorización para usar este servicio de impresión.")
        return
    
    # === 1. MANEJO DE CANCELACIÓN ===
    if query.data == "cancel_order":
        await query.edit_message_text(text="❌ Orden cancelada. Manda nuevas instrucciones si lo deseas.")
        context.user_data.pop('ultima_orden', None)
        return
    
    # === 2. MANEJO DE IMPRESIÓN ===
    if query.data.startswith("print_"):
        orden = context.user_data.get('ultima_orden')
        if not orden:
            await query.edit_message_text(text="❌ Orden caducada.")
            return
            
        # Determinar qué bandeja física se eligió
        bandeja_elegida = None
        if query.data == "print_cas1":
            bandeja_elegida = "Cassette 1"
        elif query.data == "print_cas2":
            bandeja_elegida = "Cassette 2"
        elif query.data == "print_rear":
            bandeja_elegida = "Rear Tray"
        # Si presiona "print_auto", bandeja_elegida se queda en None (FastAPI usará su lógica)
        
        # Inyectar la instrucción en el JSON de configuración
        orden['config']['bandeja_manual'] = bandeja_elegida
        
        # Cambiar el mensaje para confirmar visualmente
        modo_texto = f"Bandeja Forzada: {bandeja_elegida}" if bandeja_elegida else "Modo Automático"
        await query.edit_message_text(text=f"✅ Confirmado ({modo_texto}). 🚀 Transmitiendo por VPN...")
        
        # 💥 LA LLAMADA REAL A LA TIENDA
        exito, mensaje = await enviar_a_fastapi(orden['pdf_path'], orden['config'])
        
        if exito:
            # ✅ REGISTRO ÚNICAMENTE CUANDO SE CONFIRMÓ E IMPRIMIÓ:
            guardar_registro_csv(orden['orden_id'], orden['config'], orden['costos'])
            context.user_data.pop('ultima_orden', None) # Limpiar memoria de la orden
            await query.message.reply_text("🖨️ ¡Archivo recibido en la tienda! Imprimiendo...")
        else:
            await query.message.reply_text(f"⚠️ Falló la transmisión a la tienda:\n{mensaje}")

async def manejador_errores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atrapa los errores de red de Telegram para que no ensucien la consola."""
    print(f"⚠️ Hipo de conexión con Telegram ignorado: {context.error}")


# ================= INICIO DE LA APLICACIÓN =================
if __name__ == '__main__':
    # (Asegúrate de que load_dotenv() y os.getenv("TELEGRAM_BOT") estén hasta arriba del archivo)
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # 1. Configurar la zona horaria local (Ciudad Nezahualcóyotl / CDMX)
    tz_mexico = pytz.timezone('America/Mexico_City')
    
    # 2. Programar el Corte de Caja a las 22:05 (10:05 PM) todos los días
    hora_corte = dt_time(hour=22, minute=5, tzinfo=tz_mexico)
    app.job_queue.run_daily(enviar_corte_automatico, time=hora_corte)
    
    # 3. Gatillo de Limpieza Inmediata (Se ejecuta 5 segundos después de encender el bot por la mañana)
    app.job_queue.run_once(tarea_mantenimiento_y_limpieza, 5)
    
    # Manejador silencioso de errores
    app.add_error_handler(manejador_errores)
    # Aquí se registran todos los handlers que escuchan eventos de Telegram
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, recibir_archivo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), procesar_instruccion))
    app.add_handler(CallbackQueryHandler(boton_callback, pattern="^(print_|cancel_)"))
    
    
    print("🤖 Cerebro iniciado. Esperando archivos en Telegram...")
    app.run_polling()