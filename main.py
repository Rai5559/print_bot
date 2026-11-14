import os
import uuid
import shutil
import time
import math
import json
import re
import csv
import base64
import asyncio
from datetime import datetime, timedelta, time as dt_time
from io import BytesIO

import pytz
from dotenv import load_dotenv
import aiohttp
import numpy as np
import pandas as pd
import cv2
import pymupdf as fitz
from PIL import Image, ImageChops, ImageStat, ImageOps, ImageEnhance
from docx2pdf import convert as convert_docx
from playwright.async_api import async_playwright
import rectpack

from telegram import (
    Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)

# ================= CONFIGURACIÓN =================
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT")
BASE_DIR = "archivos_impresion"
URL_TIENDA = os.getenv("URL_TIENDA")

ids_str = os.getenv("USUARIOS_AUTORIZADOS", "")
USUARIOS_AUTORIZADOS = [int(i.strip()) for i in ids_str.split(",") if i.strip()]

WEBAPP_URL = os.getenv("WEBAPP_URL")
TECLADO_PANEL = ReplyKeyboardMarkup(
    [[KeyboardButton("🎛️ ABRIR PANEL DE IMPRESIÓN", web_app=WebAppInfo(url=WEBAPP_URL))]],
    resize_keyboard=True
)

# Memoria temporal para agrupar archivos antes de abrir la WebApp
# Estructura: {chat_id: {"archivos_temporales": [ruta1, ruta2]}}
sesiones_activas = {}

# Pixel transparente 1x1 por si se elige un layout de 3 o 5 fotos con menos imágenes
PIXEL_TRANSPARENTE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

# ================= PLANTILLAS ASIMÉTRICAS (3 Y 5 IMÁGENES) =================
PLANTILLAS_HTML = {
    # --- COMBINACIONES PARA 3 IMÁGENES ---
    "layout_asim_1_2": {  # Alias compatible con tu HTML actual (1 arriba + 2 abajo)
        "imagenes_por_hoja": 3,
        "html": """
        <div style='display:flex; flex-direction:column; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:12px;'>
            <div style='height:50%; width:100%;'><img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'></div>
            <div style='height:50%; width:100%; display:flex; gap:12px;'>
                <img src='{img_1}' style='width:50%; height:100%; object-fit:contain;'>
                <img src='{img_2}' style='width:50%; height:100%; object-fit:contain;'>
            </div>
        </div>
        """
    },
    "layout_asim_3_top": {  # 1 grande arriba + 2 abajo
        "imagenes_por_hoja": 3,
        "html": """
        <div style='display:flex; flex-direction:column; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:12px;'>
            <div style='height:52%; width:100%;'><img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'></div>
            <div style='height:48%; width:100%; display:flex; gap:12px;'>
                <img src='{img_1}' style='width:50%; height:100%; object-fit:contain;'>
                <img src='{img_2}' style='width:50%; height:100%; object-fit:contain;'>
            </div>
        </div>
        """
    },
    "layout_asim_3_bottom": {  # 2 arriba + 1 grande abajo
        "imagenes_por_hoja": 3,
        "html": """
        <div style='display:flex; flex-direction:column; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:12px;'>
            <div style='height:48%; width:100%; display:flex; gap:12px;'>
                <img src='{img_0}' style='width:50%; height:100%; object-fit:contain;'>
                <img src='{img_1}' style='width:50%; height:100%; object-fit:contain;'>
            </div>
            <div style='height:52%; width:100%;'><img src='{img_2}' style='width:100%; height:100%; object-fit:contain;'></div>
        </div>
        """
    },
    "layout_asim_3_left": {  # 1 grande izquierda + 2 apiladas derecha
        "imagenes_por_hoja": 3,
        "html": """
        <div style='display:flex; flex-direction:row; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:12px;'>
            <div style='width:52%; height:100%;'><img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'></div>
            <div style='width:48%; height:100%; display:flex; flex-direction:column; gap:12px;'>
                <img src='{img_1}' style='width:100%; height:50%; object-fit:contain;'>
                <img src='{img_2}' style='width:100%; height:50%; object-fit:contain;'>
            </div>
        </div>
        """
    },
    "layout_asim_3_right": {  # 2 apiladas izquierda + 1 grande derecha
        "imagenes_por_hoja": 3,
        "html": """
        <div style='display:flex; flex-direction:row; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:12px;'>
            <div style='width:48%; height:100%; display:flex; flex-direction:column; gap:12px;'>
                <img src='{img_0}' style='width:100%; height:50%; object-fit:contain;'>
                <img src='{img_1}' style='width:100%; height:50%; object-fit:contain;'>
            </div>
            <div style='width:52%; height:100%;'><img src='{img_2}' style='width:100%; height:100%; object-fit:contain;'></div>
        </div>
        """
    },

    # --- COMBINACIONES PARA 5 IMÁGENES ---
    "layout_asim_5_top": {  # 1 grande arriba + 4 en cuadrícula 2x2 abajo
        "imagenes_por_hoja": 5,
        "html": """
        <div style='display:flex; flex-direction:column; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:10px;'>
            <div style='height:44%; width:100%;'><img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'></div>
            <div style='height:56%; width:100%; display:grid; grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; gap:10px;'>
                <img src='{img_1}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_2}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_3}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_4}' style='width:100%; height:100%; object-fit:contain;'>
            </div>
        </div>
        """
    },
    "layout_asim_5_bottom": {  # 4 en cuadrícula 2x2 arriba + 1 grande abajo
        "imagenes_por_hoja": 5,
        "html": """
        <div style='display:flex; flex-direction:column; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:10px;'>
            <div style='height:56%; width:100%; display:grid; grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; gap:10px;'>
                <img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_1}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_2}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_3}' style='width:100%; height:100%; object-fit:contain;'>
            </div>
            <div style='height:44%; width:100%;'><img src='{img_4}' style='width:100%; height:100%; object-fit:contain;'></div>
        </div>
        """
    },
    "layout_asim_5_center": {  # 2 arriba + 1 grande panorámica al centro + 2 abajo
        "imagenes_por_hoja": 5,
        "html": """
        <div style='display:flex; flex-direction:column; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:10px;'>
            <div style='height:30%; width:100%; display:flex; gap:10px;'>
                <img src='{img_0}' style='width:50%; height:100%; object-fit:contain;'>
                <img src='{img_1}' style='width:50%; height:100%; object-fit:contain;'>
            </div>
            <div style='height:40%; width:100%;'><img src='{img_2}' style='width:100%; height:100%; object-fit:contain;'></div>
            <div style='height:30%; width:100%; display:flex; gap:10px;'>
                <img src='{img_3}' style='width:50%; height:100%; object-fit:contain;'>
                <img src='{img_4}' style='width:50%; height:100%; object-fit:contain;'>
            </div>
        </div>
        """
    },
    "layout_asim_5_left": {  # 1 grande izquierda + 4 en cuadrícula 2x2 derecha
        "imagenes_por_hoja": 5,
        "html": """
        <div style='display:flex; flex-direction:row; width:100vw; height:100vh; padding:12px; box-sizing:border-box; gap:10px;'>
            <div style='width:46%; height:100%;'><img src='{img_0}' style='width:100%; height:100%; object-fit:contain;'></div>
            <div style='width:54%; height:100%; display:grid; grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; gap:10px;'>
                <img src='{img_1}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_2}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_3}' style='width:100%; height:100%; object-fit:contain;'>
                <img src='{img_4}' style='width:100%; height:100%; object-fit:contain;'>
            </div>
        </div>
        """
    },
}

# ================= FUNCIONES CORE Y CÁLCULO DE COSTOS =================

def crear_carpetas_orden(chat_id):
    """Crea la estructura de carpetas: fecha / uuid / originales | procesados"""
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    orden_id = str(uuid.uuid4())[:8]
    ruta_originales = os.path.join(BASE_DIR, fecha_hoy, orden_id, "originales")
    ruta_procesados = os.path.join(BASE_DIR, fecha_hoy, orden_id, "procesados")
    os.makedirs(ruta_originales, exist_ok=True)
    os.makedirs(ruta_procesados, exist_ok=True)
    return orden_id, ruta_originales, ruta_procesados


def crear_lienzo(tamano="carta", orientacion="vertical"):
    """Genera el lienzo a 300 DPI según tamaño y orientación."""
    ancho, alto = 2550, 3300  # Carta
    if tamano.lower() == "oficio":
        ancho, alto = 2550, 4200
    if orientacion.lower() == "horizontal":
        ancho, alto = alto, ancho
    return Image.new("RGB", (ancho, alto), "white")


def optimizar_orientacion(img, ancho_celda, alto_celda):
    """Rota la imagen 90° solo si al girarla logra abarcar un área mayor dentro de la celda."""
    escala_normal = min(ancho_celda / img.width, alto_celda / img.height)
    escala_rotada = min(ancho_celda / img.height, alto_celda / img.width)

    # Si rotada aprovecha al menos 10% más de tamaño en el recuadro, la giramos
    if escala_rotada > (escala_normal * 1.10):
        return img.rotate(90, expand=True)
    return img


def escalar_a_celda(img, ancho_celda, alto_celda, sin_bordes=False, rotar_auto=True, margen=12):
    """
    Aumenta o reduce cualquier imagen para que abarque el máximo espacio posible
    de su celda asignada sin deformarse (mantiene relación de aspecto exacta).
    """
    if rotar_auto:
        img = optimizar_orientacion(img, ancho_celda, alto_celda)

    w_util = max(1, ancho_celda if sin_bordes else (ancho_celda - margen * 2))
    h_util = max(1, alto_celda if sin_bordes else (alto_celda - margen * 2))

    if sin_bordes:
        # Cubre el 100% de la celda recortando únicamente el sobrante centrado
        return ImageOps.fit(img, (w_util, h_util), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    # Cálculo explícito de ampliación/reducción proporcional sin deformar
    factor = min(w_util / img.width, h_util / img.height)
    nuevo_w = max(1, int(round(img.width * factor)))
    nuevo_h = max(1, int(round(img.height * factor)))

    return img.resize((nuevo_w, nuevo_h), resample=Image.Resampling.LANCZOS)


def pegar_en_caja(hoja, img, x_caja, y_caja, w_caja, h_caja, sin_bordes=False, rotar_auto=True, margen=12):
    """Escala la imagen al máximo de la caja y la pega perfectamente centrada."""
    if img is None:
        return
    img_escalada = escalar_a_celda(img, w_caja, h_caja, sin_bordes=sin_bordes, rotar_auto=rotar_auto, margen=margen)
    x_offset = x_caja + (w_caja - img_escalada.width) // 2
    y_offset = y_caja + (h_caja - img_escalada.height) // 2
    hoja.paste(img_escalada, (x_offset, y_offset))


def obtener_cajas_asimetricas(layout_id, ancho_hoja, alto_hoja, escala=1.0):
    """Devuelve las coordenadas exactas (x, y, w, h) de cada recuadro para layouts de 3 y 5 fotos."""
    margen_ext = 40
    gap = 24

    W = int((ancho_hoja - (margen_ext * 2)) * escala)
    H = int((alto_hoja - (margen_ext * 2)) * escala)
    x0 = (ancho_hoja - W) // 2
    y0 = margen_ext if escala < 1.0 else (alto_hoja - H) // 2

    w_mitad = (W - gap) // 2
    h_mitad = (H - gap) // 2

    # --- LAYOUTS DE 3 IMÁGENES ---
    if layout_id in ["layout_asim_3_top", "layout_asim_1_2"]:
        h_top = int((H - gap) * 0.52)
        h_bot = (H - gap) - h_top
        return [
            (x0, y0, W, h_top),
            (x0, y0 + h_top + gap, w_mitad, h_bot),
            (x0 + w_mitad + gap, y0 + h_top + gap, w_mitad, h_bot),
        ]

    if layout_id == "layout_asim_3_bottom":
        h_top = int((H - gap) * 0.48)
        h_bot = (H - gap) - h_top
        return [
            (x0, y0, w_mitad, h_top),
            (x0 + w_mitad + gap, y0, w_mitad, h_top),
            (x0, y0 + h_top + gap, W, h_bot),
        ]

    if layout_id == "layout_asim_3_left":
        w_left = int((W - gap) * 0.52)
        w_right = (W - gap) - w_left
        return [
            (x0, y0, w_left, H),
            (x0 + w_left + gap, y0, w_right, h_mitad),
            (x0 + w_left + gap, y0 + h_mitad + gap, w_right, h_mitad),
        ]

    if layout_id == "layout_asim_3_right":
        w_left = int((W - gap) * 0.48)
        w_right = (W - gap) - w_left
        return [
            (x0, y0, w_left, h_mitad),
            (x0, y0 + h_mitad + gap, w_left, h_mitad),
            (x0 + w_left + gap, y0, w_right, H),
        ]

    # --- LAYOUTS DE 5 IMÁGENES ---
    if layout_id == "layout_asim_5_top":
        h_top = int((H - gap) * 0.44)
        h_bot = (H - gap) - h_top
        h_celda = (h_bot - gap) // 2
        y_grid = y0 + h_top + gap
        return [
            (x0, y0, W, h_top),
            (x0, y_grid, w_mitad, h_celda),
            (x0 + w_mitad + gap, y_grid, w_mitad, h_celda),
            (x0, y_grid + h_celda + gap, w_mitad, h_celda),
            (x0 + w_mitad + gap, y_grid + h_celda + gap, w_mitad, h_celda),
        ]

    if layout_id == "layout_asim_5_bottom":
        h_top = int((H - gap) * 0.56)
        h_bot = (H - gap) - h_top
        h_celda = (h_top - gap) // 2
        return [
            (x0, y0, w_mitad, h_celda),
            (x0 + w_mitad + gap, y0, w_mitad, h_celda),
            (x0, y0 + h_celda + gap, w_mitad, h_celda),
            (x0 + w_mitad + gap, y0 + h_celda + gap, w_mitad, h_celda),
            (x0, y0 + h_top + gap, W, h_bot),
        ]

    if layout_id == "layout_asim_5_center":
        h_disp = H - (gap * 2)
        h_fila1 = int(h_disp * 0.30)
        h_centro = int(h_disp * 0.40)
        h_fila3 = h_disp - h_fila1 - h_centro
        y_centro = y0 + h_fila1 + gap
        y_fila3 = y_centro + h_centro + gap
        return [
            (x0, y0, w_mitad, h_fila1),
            (x0 + w_mitad + gap, y0, w_mitad, h_fila1),
            (x0, y_centro, W, h_centro),
            (x0, y_fila3, w_mitad, h_fila3),
            (x0 + w_mitad + gap, y_fila3, w_mitad, h_fila3),
        ]

    if layout_id == "layout_asim_5_left":
        w_left = int((W - gap) * 0.46)
        w_right = (W - gap) - w_left
        w_celda = (w_right - gap) // 2
        x_grid = x0 + w_left + gap
        return [
            (x0, y0, w_left, H),
            (x_grid, y0, w_celda, h_mitad),
            (x_grid + w_celda + gap, y0, w_celda, h_mitad),
            (x_grid, y0 + h_mitad + gap, w_celda, h_mitad),
            (x_grid + w_celda + gap, y0 + h_mitad + gap, w_celda, h_mitad),
        ]

    return [(x0, y0, W, H)]


def obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, num_slots):
    """Devuelve una lista de longitud num_slots con las imágenes elegidas o None si el slot es X (-1)."""
    resultado = []
    for slot in range(num_slots):
        foto_idx = int(mapa_usuario.get(str(slot), -1))
        if 0 <= foto_idx < len(todas_las_imagenes):
            resultado.append(todas_las_imagenes[foto_idx])
        else:
            resultado.append(None)
    return resultado


def analizar_rango(rango_val, total_paginas):
    """Convierte cadenas como '1-5, 8, 12-15' en índices base 0 válidos."""
    if not rango_val or str(rango_val).lower().strip() in ["todos", "todas", "todo", "null", "none", "[]", ""]:
        return None
    paginas_a_imprimir = set()
    rango_str = ",".join(str(x) for x in rango_val) if isinstance(rango_val, list) else str(rango_val)
    rango_limpio = rango_str.lower().replace(" y ", ",").replace(" e ", ",").replace("&", ",")
    rango_limpio = rango_limpio.replace(" al ", "-").replace(" a ", "-")
    rango_limpio = re.sub(r'[^\d,\-]', '', rango_limpio)

    for parte in rango_limpio.split(","):
        if "-" in parte:
            try:
                nums = [int(n) for n in parte.split("-") if n]
                if len(nums) >= 2:
                    inicio, fin = min(nums[0], nums[1]), max(nums[0], nums[1])
                    for p in range(inicio - 1, fin):
                        if 0 <= p < total_paginas:
                            paginas_a_imprimir.add(p)
            except Exception:
                pass
        elif parte:
            try:
                p = int(parte) - 1
                if 0 <= p < total_paginas:
                    paginas_a_imprimir.add(p)
            except Exception:
                pass

    return sorted(list(paginas_a_imprimir)) if paginas_a_imprimir else None


def guardar_registro_csv(orden_id, config, costos):
    """Guarda silenciosamente la orden confirmada en la base de datos local CSV."""
    archivo_csv = "registro_impresiones.csv"
    existe = os.path.isfile(archivo_csv)
    with open(archivo_csv, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not existe:
            writer.writerow([
                "Fecha", "Hora", "Orden_ID", "Tamano", "Tipo_Papel",
                "Copias", "Hojas_Fisicas", "Pags_BN", "Pags_Color", "Pags_Foto",
                "Costo_Total", "Venta_Total", "Ganancia"
            ])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M:%S"),
            orden_id,
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
    """Mejora automática para credenciales: mantiene color pero limpia fondos grises."""
    img = img.convert("RGB")
    img = ImageOps.autocontrast(img, cutoff=1)
    return ImageEnhance.Brightness(img).enhance(1.2)


def limpiar_documento_opencv(img):
    """Convierte fotos oscuras con sombras en documentos escaneados puros (B/N)."""
    img_cv = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        21, 15
    )
    return Image.fromarray(thresh).convert("RGB")


def analizar_cobertura_pagina(page):
    """Calcula el % exacto de tinta a color y B/N mediante NumPy."""
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csRGB)
    img_array = np.array(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    mascara_blanca = np.all(img_array > 240, axis=-1)
    diferencia = np.max(img_array, axis=-1).astype(int) - np.min(img_array, axis=-1).astype(int)
    total_pixeles = img_array.shape[0] * img_array.shape[1]
    cobertura_color = np.sum((diferencia > 15) & (~mascara_blanca)) / total_pixeles
    cobertura_bn = np.sum((diferencia <= 15) & (~mascara_blanca)) / total_pixeles
    return cobertura_color, cobertura_bn


def calcular_costo_gx7110(pdf_path, config_json):
    """Calcula precios dinámicos basándose en el consumo exacto de tinta."""
    doc = fitz.open(pdf_path)
    num_paginas = len(doc)
    copias = config_json.get("copias", 1)
    doble_cara = config_json.get("doble_cara", False)
    es_fotografico = config_json.get("tipo_papel") == "fotografico"
    forzar_bn = not config_json.get("color", False)

    costo_tinta_total = 0.0
    precio_venta_total = 0.0
    resumen = {"texto_bn": 0, "texto_color": 0, "imagen_full": 0}

    costo_100pct_color = 1.50 if es_fotografico else 1.00
    costo_100pct_bn = 0.60

    for i in range(num_paginas):
        cob_color, cob_bn = analizar_cobertura_pagina(doc[i])
        if forzar_bn:
            cob_bn += cob_color
            cob_color = 0.0

        costo_tinta_total += (cob_color * costo_100pct_color) + (cob_bn * costo_100pct_bn)

        if es_fotografico:
            precio_pag = 15.00
            resumen["imagen_full"] += 1
        elif cob_color > 0.15:
            precio_pag = 6.00
            resumen["imagen_full"] += 1
        elif cob_color > 0.01:
            precio_pag = 3.00
            resumen["texto_color"] += 1
        else:
            precio_pag = 1.50
            resumen["texto_bn"] += 1

        precio_venta_total += precio_pag

    doc.close()

    hojas_por_copia = math.ceil(num_paginas / 2) if doble_cara else num_paginas
    total_hojas = hojas_por_copia * copias
    costo_hoja = 3.00 if es_fotografico else 0.30
    costo_interno = (total_hojas * costo_hoja) + (costo_tinta_total * copias)
    precio_venta = precio_venta_total * copias

    return {
        "paginas_totales": num_paginas * copias,
        "resumen_tipos": {k: v * copias for k, v in resumen.items()},
        "hojas_fisicas_a_usar": total_hojas,
        "costo_interno_mxn": round(costo_interno, 2),
        "precio_venta_sugerido": round(precio_venta, 2),
        "ganancia_estimada": round(precio_venta - costo_interno, 2)
    }


# ================= ENRUTADOR WEBAPP A CONFIGURACIÓN EXACTA =================

def normalizar_bandeja(valor_bandeja):
    """Traduce el valor de bandeja de la UI a lo que espera FastAPI."""
    if not valor_bandeja:
        return None
    val = str(valor_bandeja).lower().strip()
    if val in ["cas1", "cassette 1", "cassette1"]:
        return "Cassette 1"
    if val in ["cas2", "cassette 2", "cassette2"]:
        return "Cassette 2"
    if val in ["rear", "rear tray", "posterior", "bandeja posterior"]:
        return "Rear Tray"
    return None


def mapear_webapp_a_config(data_webapp, num_archivos):
    """Traduce el JSON enviado por la WebApp a la configuración completa del motor."""
    mapa_slots = data_webapp.get("mapa_slots", {})
    acomodo_manual = bool(data_webapp.get("acomodo_manual", False))

    c = {
        "mapa_slots": mapa_slots,
        "acomodo_manual": acomodo_manual,
        "copias": max(1, int(data_webapp.get("copias", 1))),
        "color": bool(data_webapp.get("color", False)),
        "tamano_papel": str(data_webapp.get("tamano_papel", "carta")).lower(),
        "tipo_papel": str(data_webapp.get("tipo_papel", "normal")).lower(),
        "doble_cara": bool(data_webapp.get("doble_cara", False)),
        "sin_bordes": bool(data_webapp.get("sin_bordes", False)),
        "modo_escaner": bool(data_webapp.get("modo_escaner", False)),
        "rango_paginas": str(data_webapp.get("rango", "")).strip(),
        "bandeja_manual": normalizar_bandeja(data_webapp.get("bandeja")),
        # Valores por defecto de acomodo
        "layout_n_up": 1,
        "columnas_forzadas": None,
        "filas_forzadas": None,
        "orientacion": str(data_webapp.get("orientacion", "vertical")).lower(),
        "forzar_rotacion": str(data_webapp.get("forzar_rotacion", "ninguna")).lower(),
        "escala_porcentaje": int(data_webapp.get("escala_porcentaje", 100)),
        "modo_html": False,
        "codigo_html": "",
        "imagenes_por_hoja": 1,
        "modo_tetris": bool(data_webapp.get("modo_tetris", False)),
        "modo_planilla": False,
        "dimensiones_cm": None,
        "repeticiones": int(data_webapp.get("repeticiones", 0)),
        "tipo_documento": "ine" if data_webapp.get("modo_ine") else "normal",
    }

    lid = str(data_webapp.get("layout_id", "layout_1"))
    c["layout_id"] = lid
    # 1. Cuadrículas estándar
    if lid == "layout_1":
        c["layout_n_up"] = 1
    elif lid == "layout_2_horiz":  # 2 Apiladas (1 col, 2 filas)
        c["layout_n_up"] = 2
        c["columnas_forzadas"] = 1
        c["filas_forzadas"] = 2
    elif lid == "layout_2_vert":  # 2 Lado a Lado (2 cols, 1 fila)
        c["layout_n_up"] = 2
        c["columnas_forzadas"] = 2
        c["filas_forzadas"] = 1
    elif lid == "layout_4":
        c["layout_n_up"] = 4
        c["columnas_forzadas"] = 2
        c["filas_forzadas"] = 2
    elif lid == "layout_6":
        c["layout_n_up"] = 6
        c["columnas_forzadas"] = 2
        c["filas_forzadas"] = 3
    elif lid == "layout_8":
        c["layout_n_up"] = 8
        c["columnas_forzadas"] = 2
        c["filas_forzadas"] = 4

    # 2. Planillas de medidas exactas
    elif lid == "planilla_infantil":
        c["modo_planilla"] = True
        c["dimensiones_cm"] = [2.5, 3.0]
        c["repeticiones"] = int(data_webapp.get("repeticiones", 0))
    elif lid == "planilla_pasaporte":
        c["modo_planilla"] = True
        c["dimensiones_cm"] = [3.5, 4.5]
        c["repeticiones"] = int(data_webapp.get("repeticiones", 0))
    elif lid == "planilla_custom":
        ancho_cm = float(data_webapp.get("ancho_cm", 5.0))
        alto_cm = float(data_webapp.get("alto_cm", 5.0))
        c["modo_planilla"] = True
        c["dimensiones_cm"] = [ancho_cm, alto_cm]
        c["repeticiones"] = int(data_webapp.get("repeticiones", 0))

    # 3. Layouts asimétricos (3 y 5 imágenes)
    elif lid in PLANTILLAS_HTML:
        plantilla = PLANTILLAS_HTML[lid]
        c["modo_html"] = True
        c["codigo_html"] = plantilla["html"]
        c["imagenes_por_hoja"] = plantilla["imagenes_por_hoja"]

    # 4. Todo en 1 hoja automático o con lienzo interactivo
    if data_webapp.get("modo_todo_en_uno"):
        c["layout_n_up"] = len(mapa_slots) if (acomodo_manual and mapa_slots) else max(1, num_archivos)
        c["columnas_forzadas"] = None
        c["filas_forzadas"] = None

    return c


def obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, num_slots):
    """Devuelve una lista de longitud num_slots con las imágenes elegidas o None si el slot es X (-1)."""
    resultado = []
    for slot in range(num_slots):
        foto_idx = int(mapa_usuario.get(str(slot), -1))
        if 0 <= foto_idx < len(todas_las_imagenes):
            resultado.append(todas_las_imagenes[foto_idx])
        else:
            resultado.append(None)
    return resultado


# ================= MOTOR DE GENERACIÓN PDF =================

async def unificar_y_procesar_a_pdf(lista_archivos, ruta_procesados, config_json):
    ruta_salida = os.path.join(ruta_procesados, "documento_final.pdf")
    layout_n = config_json.get("layout_n_up", 1)
    layout_id = config_json.get("layout_id", "layout_1")
    tamano_papel = config_json.get("tamano_papel", "carta")
    orientacion = config_json.get("orientacion", "vertical")
    tipo_doc = config_json.get("tipo_documento", "normal").lower()
    escala = config_json.get("escala_porcentaje", 100) / 100.0
    forzar_rotacion = config_json.get("forzar_rotacion", "ninguna")
    sin_bordes = config_json.get("sin_bordes", False)
    mapa_usuario = config_json.get("mapa_slots", {})
    acomodo_manual = config_json.get("acomodo_manual", False)
    rotar_auto = (forzar_rotacion == "ninguna")

    todas_las_imagenes = []

    # 1. EXTRACCIÓN Y FILTRO DE PÁGINAS
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
            rango_str = config_json.get("rango_paginas", "")
            doc = fitz.open(archivo_a_procesar)
            paginas_validas = analizar_rango(rango_str, len(doc))

            for i in range(len(doc)):
                if paginas_validas is not None and i not in paginas_validas:
                    continue
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(4.16, 4.16))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                todas_las_imagenes.append(img)
            doc.close()
        else:
            todas_las_imagenes.append(Image.open(archivo_a_procesar).convert("RGB"))

    if not todas_las_imagenes:
        crear_lienzo(tamano_papel, orientacion).save(ruta_salida, resolution=300.0)
        return ruta_salida

    # 2. PRE-PROCESAMIENTO: ROTACIÓN FORZADA
    for idx, img in enumerate(todas_las_imagenes):
        if forzar_rotacion == "vertical" and img.width > img.height:
            todas_las_imagenes[idx] = img.rotate(90, expand=True)
        elif forzar_rotacion == "horizontal" and img.height > img.width:
            todas_las_imagenes[idx] = img.rotate(90, expand=True)

    # 3. MEJORA VISUAL AUTOMÁTICA (MODO ESCÁNER / INE)
    modo_escaner = config_json.get("modo_escaner", False)
    for idx, img in enumerate(todas_las_imagenes):
        if tipo_doc == "ine":
            todas_las_imagenes[idx] = mejorar_contraste_ine(img)
        elif modo_escaner:
            todas_las_imagenes[idx] = limpiar_documento_opencv(img)

    # 4. CARRIL LAYOUTS ASIMÉTRICOS (3 y 5 IMÁGENES EN PILLOW A 300 DPI)
    if config_json.get("modo_html", False) or layout_id.startswith("layout_asim_"):
        imgs_por_hoja = 3 if "_3_" in layout_id or layout_id == "layout_asim_1_2" else 5

        if acomodo_manual and mapa_usuario:
            lotes_asim = [obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, imgs_por_hoja)]
        else:
            lotes_asim = [todas_las_imagenes[i:i + imgs_por_hoja] for i in range(0, len(todas_las_imagenes), imgs_por_hoja)]

        paginas_pdf = []
        for lote in lotes_asim:
            hoja = crear_lienzo(tamano_papel, orientacion)
            cajas = obtener_cajas_asimetricas(layout_id, hoja.width, hoja.height, escala=escala)
            for idx, (x_c, y_c, w_c, h_c) in enumerate(cajas):
                img_slot = lote[idx] if idx < len(lote) else None
                pegar_en_caja(hoja, img_slot, x_c, y_c, w_c, h_c, sin_bordes=sin_bordes, rotar_auto=rotar_auto, margen=8)
            paginas_pdf.append(hoja)

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 5. CARRIL TETRIS MATEMÁTICO CON AUTO-AMPLIACIÓN PROPORCIONAL
    if config_json.get("modo_tetris", False):
        if acomodo_manual and mapa_usuario:
            imagenes_tetris = [
                img for img in obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, len(mapa_usuario))
                if img is not None
            ]
        else:
            imagenes_tetris = list(todas_las_imagenes)

        if not imagenes_tetris:
            crear_lienzo(tamano_papel, orientacion).save(ruta_salida, resolution=300.0)
            return ruta_salida

        espaciado = 20
        margen_seguro = 50
        hoja_prueba = crear_lienzo(tamano_papel, orientacion)
        ancho_util = hoja_prueba.width - (margen_seguro * 2)
        alto_util = hoja_prueba.height - (margen_seguro * 2)

        # Paso A: Si alguna imagen excede el tamaño de la hoja, reducirla para que nunca se descarte
        imgs_normalizadas = []
        for img in imagenes_tetris:
            f_max = min((ancho_util - espaciado) / img.width, (alto_util - espaciado) / img.height)
            if f_max < 1.0:
                img = img.resize((max(1, int(img.width * f_max)), max(1, int(img.height * f_max))), Image.Resampling.LANCZOS)
            imgs_normalizadas.append(img)

        # Paso B: Si las imágenes son pequeñas, buscar el factor máximo de ampliación que quepa en 1 hoja
        def empaquetar_con_factor(factor_prueba):
            p = rectpack.newPacker(rotation=True)
            for idx, im in enumerate(imgs_normalizadas):
                w_p = max(1, int(im.width * factor_prueba)) + espaciado
                h_p = max(1, int(im.height * factor_prueba)) + espaciado
                if min(w_p, h_p) > min(ancho_util, alto_util) or max(w_p, h_p) > max(ancho_util, alto_util):
                    return None
                p.add_rect(w_p, h_p, rid=idx)
            for _ in range(len(imgs_normalizadas)):
                p.add_bin(ancho_util, alto_util)
            p.pack()
            return p

        packer_base = empaquetar_con_factor(1.0)
        factor_optimo = 1.0
        if packer_base and len(packer_base) == 1:
            low, high = 1.0, 6.0
            for _ in range(10):
                mid = (low + high) / 2
                p_test = empaquetar_con_factor(mid)
                if p_test and len(p_test) == 1 and len(p_test[0]) == len(imgs_normalizadas):
                    factor_optimo = mid
                    low = mid
                else:
                    high = mid

        packer = empaquetar_con_factor(factor_optimo) or packer_base

        paginas_pdf = []
        for bin_pack in packer:
            hoja = crear_lienzo(tamano_papel, orientacion)
            for rect in bin_pack:
                w_caja = rect.width - espaciado
                h_caja = rect.height - espaciado
                img_orig = imgs_normalizadas[rect.rid]
                pegar_en_caja(
                    hoja, img_orig,
                    margen_seguro + rect.x, margen_seguro + rect.y,
                    w_caja, h_caja,
                    sin_bordes=sin_bordes, rotar_auto=True, margen=0
                )
            paginas_pdf.append(hoja)

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 6. CARRIL COPIA DE INE / CREDENCIALES
    if tipo_doc == "ine":
        ancho_ine = int(1015 * escala)
        alto_ine = int(638 * escala)

        if acomodo_manual and mapa_usuario:
            lotes_ine = [obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, 2)]
        else:
            lotes_ine = [todas_las_imagenes[i:i + 2] for i in range(0, len(todas_las_imagenes), 2)]

        paginas_pdf = []
        for lote in lotes_ine:
            hoja = crear_lienzo(tamano_papel, orientacion)
            for idx, img in enumerate(lote):
                if img is None:
                    continue
                x_caja = (hoja.width - ancho_ine) // 2
                y_caja = (hoja.height // 2) * idx + ((hoja.height // 2) - alto_ine) // 2
                pegar_en_caja(hoja, img, x_caja, y_caja, ancho_ine, alto_ine, sin_bordes=sin_bordes, rotar_auto=True, margen=0)
            paginas_pdf.append(hoja)

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 7. CARRIL PLANILLAS INFANTILES / PASAPORTE / EXACTAS
    if config_json.get("modo_planilla", False) or config_json.get("dimensiones_cm"):
        DPI_CM = 118.11
        dims = config_json.get("dimensiones_cm")
        if dims and isinstance(dims, list) and len(dims) == 2:
            ancho_px = int(dims[0] * DPI_CM)
            alto_px = int(dims[1] * DPI_CM)
        else:
            ancho_px = int(10 * DPI_CM)
            alto_px = int(15 * DPI_CM)

        espaciado = 20
        margen = 100
        hoja_actual = crear_lienzo(tamano_papel, orientacion)
        cols = max(1, (hoja_actual.width - (margen * 2)) // (ancho_px + espaciado))
        filas = max(1, (hoja_actual.height - (margen * 2)) // (alto_px + espaciado))
        capacidad_hoja = cols * filas

        repeticiones = config_json.get("repeticiones", 0)
        lista_imprimir = []

        if repeticiones == 0:
            if acomodo_manual and mapa_usuario:
                fotos_base = [
                    img for img in obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, len(mapa_usuario))
                    if img is not None
                ]
            else:
                fotos_base = todas_las_imagenes
            if not fotos_base:
                fotos_base = todas_las_imagenes

            rep_por_img = max(1, capacidad_hoja // len(fotos_base))
            for img in fotos_base:
                img_rec = escalar_a_celda(img, ancho_px, alto_px, sin_bordes=sin_bordes, rotar_auto=rotar_auto, margen=0)
                lista_imprimir.extend([img_rec] * rep_por_img)
        else:
            if acomodo_manual and mapa_usuario:
                slots_planilla = obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, len(mapa_usuario))
                for img in slots_planilla:
                    if img is not None:
                        lista_imprimir.append(escalar_a_celda(img, ancho_px, alto_px, sin_bordes=sin_bordes, rotar_auto=rotar_auto, margen=0))
                    else:
                        lista_imprimir.append(None)
            else:
                for img in todas_las_imagenes:
                    img_rec = escalar_a_celda(img, ancho_px, alto_px, sin_bordes=sin_bordes, rotar_auto=rotar_auto, margen=0)
                    lista_imprimir.extend([img_rec] * repeticiones)

        paginas_pdf = []
        dibujadas = 0
        for i, img in enumerate(lista_imprimir):
            if img is not None:
                x_caja = margen + ((dibujadas % cols) * (ancho_px + espaciado))
                y_caja = margen + ((dibujadas // cols) * (alto_px + espaciado))
                x_offset = x_caja + (ancho_px - img.width) // 2
                y_offset = y_caja + (alto_px - img.height) // 2
                hoja_actual.paste(img, (x_offset, y_offset))
            dibujadas += 1

            if dibujadas >= capacidad_hoja or i == len(lista_imprimir) - 1:
                paginas_pdf.append(hoja_actual)
                if i != len(lista_imprimir) - 1:
                    hoja_actual = crear_lienzo(tamano_papel, orientacion)
                    dibujadas = 0

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 8. CARRIL CUADRÍCULA ESTÁNDAR (1, 2, 4, 6, 8, TODO EN 1)
    if config_json.get("columnas_forzadas") and config_json.get("filas_forzadas"):
        columnas = config_json["columnas_forzadas"]
        filas = config_json["filas_forzadas"]
    else:
        img_ejemplo = todas_las_imagenes[0]
        es_img_horizontal = img_ejemplo.width > img_ejemplo.height
        columnas, filas = 1, 1
        if layout_n == 2:
            columnas, filas = (1, 2) if (orientacion == "vertical") == es_img_horizontal else (2, 1)
        elif layout_n > 2:
            columnas = 2
            filas = math.ceil(layout_n / 2)

    if acomodo_manual and mapa_usuario:
        num_slots_grid = max(layout_n, len(mapa_usuario))
        lotes_grid = [obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, num_slots_grid)]
    else:
        lotes_grid = [todas_las_imagenes[i:i + layout_n] for i in range(0, len(todas_las_imagenes), layout_n)]

    paginas_pdf = []
    for lote in lotes_grid:
        hoja = crear_lienzo(tamano_papel, orientacion)
        w_celda = int((hoja.width // columnas) * escala)
        h_celda = int((hoja.height // filas) * escala)

        y_start = 150 if escala < 1.0 else 0
        x_start = (hoja.width - (w_celda * columnas)) // 2 if escala < 1.0 else 0
        margen_celda = 15 if escala >= 1.0 else 4

        for idx, img in enumerate(lote):
            if img is None:
                continue
            x_base = x_start + ((idx % columnas) * w_celda)
            y_base = y_start + ((idx // columnas) * h_celda)
            pegar_en_caja(
                hoja, img,
                x_base, y_base, w_celda, h_celda,
                sin_bordes=sin_bordes, rotar_auto=rotar_auto, margen=margen_celda
            )
        paginas_pdf.append(hoja)

    if paginas_pdf:
        paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
    return ruta_salida

    # 5. CARRIL TETRIS MATEMÁTICO (BIN PACKING)
    if config_json.get("modo_tetris", False):
        if acomodo_manual and mapa_usuario:
            imagenes_tetris = [
                img for img in obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, len(mapa_usuario))
                if img is not None
            ]
        else:
            imagenes_tetris = todas_las_imagenes

        if not imagenes_tetris:
            crear_lienzo(tamano_papel, orientacion).save(ruta_salida, resolution=300.0)
            return ruta_salida

        espaciado = 20
        margen_seguro = 50
        hoja_prueba = crear_lienzo(tamano_papel, orientacion)
        packer = rectpack.newPacker(rotation=True)

        for idx, img in enumerate(imagenes_tetris):
            packer.add_rect(img.width + espaciado, img.height + espaciado, rid=idx)
        for _ in range(len(imagenes_tetris)):
            packer.add_bin(hoja_prueba.width - (margen_seguro * 2), hoja_prueba.height - (margen_seguro * 2))
        packer.pack()

        paginas_pdf = []
        for bin_pack in packer:
            hoja = crear_lienzo(tamano_papel, orientacion)
            for rect in bin_pack:
                img = imagenes_tetris[rect.rid]
                if rect.width != (img.width + espaciado):
                    img = img.rotate(90, expand=True)
                hoja.paste(img, (margen_seguro + rect.x, margen_seguro + rect.y))
            paginas_pdf.append(hoja)

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 6. CARRIL COPIA DE INE / CREDENCIALES (SOPORTA POSICIÓN SUPERIOR/INFERIOR Y HUECOS VACÍOS)
    if tipo_doc == "ine":
        ancho_ine = int(1015 * escala)
        alto_ine = int(638 * escala)

        if acomodo_manual and mapa_usuario:
            lotes_ine = [obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, 2)]
        else:
            lotes_ine = [todas_las_imagenes[i:i + 2] for i in range(0, len(todas_las_imagenes), 2)]

        paginas_pdf = []
        for lote in lotes_ine:
            hoja = crear_lienzo(tamano_papel, orientacion)
            for idx, img in enumerate(lote):
                if img is None:
                    continue
                if img.height > img.width:
                    img = img.rotate(90, expand=True)
                img_opt = ImageOps.pad(img, (ancho_ine, alto_ine), method=Image.Resampling.LANCZOS, color="white")
                x_offset = (hoja.width - img_opt.width) // 2
                y_base = (hoja.height // 2) * idx
                y_offset = y_base + ((hoja.height // 2) - img_opt.height) // 2
                hoja.paste(img_opt, (x_offset, y_offset))
            paginas_pdf.append(hoja)

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 7. CARRIL PLANILLAS INFANTILES / PASAPORTE / EXACTAS
    if config_json.get("modo_planilla", False) or config_json.get("dimensiones_cm"):
        DPI_CM = 118.11
        dims = config_json.get("dimensiones_cm")
        if dims and isinstance(dims, list) and len(dims) == 2:
            ancho_px = int(dims[0] * DPI_CM)
            alto_px = int(dims[1] * DPI_CM)
        else:
            ancho_px = int(10 * DPI_CM)
            alto_px = int(15 * DPI_CM)

        espaciado = 20
        margen = 100
        hoja_actual = crear_lienzo(tamano_papel, orientacion)
        cols = max(1, (hoja_actual.width - (margen * 2)) // (ancho_px + espaciado))
        filas = max(1, (hoja_actual.height - (margen * 2)) // (alto_px + espaciado))
        capacidad_hoja = cols * filas

        repeticiones = config_json.get("repeticiones", 0)
        lista_imprimir = []

        if repeticiones == 0:
            # Modo llenar hoja: usa las fotos activas en el lienzo
            if acomodo_manual and mapa_usuario:
                fotos_base = [
                    img for img in obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, len(mapa_usuario))
                    if img is not None
                ]
            else:
                fotos_base = todas_las_imagenes

            if not fotos_base:
                fotos_base = todas_las_imagenes

            rep_por_img = max(1, capacidad_hoja // len(fotos_base))
            for img in fotos_base:
                img_rec = ImageOps.pad(img, (ancho_px, alto_px), method=Image.Resampling.LANCZOS, color="white")
                lista_imprimir.extend([img_rec] * rep_por_img)
        else:
            # Repeticiones fijas: si modificó el lienzo, respeta cada casilla (incluso huecos vacíos X)
            if acomodo_manual and mapa_usuario:
                slots_planilla = obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, len(mapa_usuario))
                for img in slots_planilla:
                    if img is not None:
                        lista_imprimir.append(ImageOps.pad(img, (ancho_px, alto_px), method=Image.Resampling.LANCZOS, color="white"))
                    else:
                        lista_imprimir.append(None)
            else:
                for img in todas_las_imagenes:
                    img_rec = ImageOps.pad(img, (ancho_px, alto_px), method=Image.Resampling.LANCZOS, color="white")
                    lista_imprimir.extend([img_rec] * repeticiones)

        paginas_pdf = []
        dibujadas = 0
        for i, img in enumerate(lista_imprimir):
            if img is not None:
                x_pos = margen + ((dibujadas % cols) * (ancho_px + espaciado))
                y_pos = margen + ((dibujadas // cols) * (alto_px + espaciado))
                hoja_actual.paste(img, (x_pos, y_pos))
            dibujadas += 1

            if dibujadas >= capacidad_hoja or i == len(lista_imprimir) - 1:
                paginas_pdf.append(hoja_actual)
                if i != len(lista_imprimir) - 1:
                    hoja_actual = crear_lienzo(tamano_papel, orientacion)
                    dibujadas = 0

        if paginas_pdf:
            paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
        return ruta_salida

    # 8. CARRIL CUADRÍCULA ESTÁNDAR (1, 2, 4, 6, 8, TODO EN 1) CON SOPORTE DE LIENZO INTERACTIVO
    if config_json.get("columnas_forzadas") and config_json.get("filas_forzadas"):
        columnas = config_json["columnas_forzadas"]
        filas = config_json["filas_forzadas"]
    else:
        img_ejemplo = todas_las_imagenes[0]
        es_img_horizontal = img_ejemplo.width > img_ejemplo.height
        columnas, filas = 1, 1
        if layout_n == 2:
            columnas, filas = (1, 2) if (orientacion == "vertical") == es_img_horizontal else (2, 1)
        elif layout_n > 2:
            columnas = 2
            filas = math.ceil(layout_n / 2)

    # Si el usuario personalizó el lienzo, armamos la hoja exacta con sus posiciones y huecos (None)
    if acomodo_manual and mapa_usuario:
        num_slots_grid = max(layout_n, len(mapa_usuario))
        lotes_grid = [obtener_slots_personalizados(todas_las_imagenes, mapa_usuario, num_slots_grid)]
    else:
        lotes_grid = [todas_las_imagenes[i:i + layout_n] for i in range(0, len(todas_las_imagenes), layout_n)]

    paginas_pdf = []
    sin_bordes = config_json.get("sin_bordes", False)

    for lote in lotes_grid:
        hoja = crear_lienzo(tamano_papel, orientacion)
        w_celda = int((hoja.width // columnas) * escala)
        h_celda = int((hoja.height // filas) * escala)

        y_start = 150 if escala < 1.0 else 0
        x_start = (hoja.width - (w_celda * columnas)) // 2 if escala < 1.0 else 0

        for idx, img in enumerate(lote):
            if img is None:
                continue  # Deja esta celda completamente en blanco y conserva las coordenadas del resto
            img_opt = optimizar_orientacion(img, w_celda, h_celda)
            if sin_bordes:
                img_opt = ImageOps.fit(
                    img_opt, (w_celda, h_celda),
                    method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
                )
            else:
                margen = 15 if escala >= 1.0 else 0
                img_opt = ImageOps.contain(
                    img_opt, (w_celda - margen * 2, h_celda - margen * 2),
                    method=Image.Resampling.LANCZOS
                )
            x_base = x_start + ((idx % columnas) * w_celda)
            y_base = y_start + ((idx // columnas) * h_celda)
            hoja.paste(img_opt, (x_base + (w_celda - img_opt.width) // 2, y_base + (h_celda - img_opt.height) // 2))
        paginas_pdf.append(hoja)

    if paginas_pdf:
        paginas_pdf[0].save(ruta_salida, save_all=True, append_images=paginas_pdf[1:], resolution=300.0)
    return ruta_salida


# ================= COMUNICACIÓN CON TIENDA Y REPORTES =================

async def enviar_a_fastapi(pdf_path, config_json):
    """Envía el PDF final y la configuración a la PC de la tienda vía WireGuard."""
    try:
        async with aiohttp.ClientSession() as session:
            with open(pdf_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('archivo', f, filename=os.path.basename(pdf_path))
                data.add_field('config', json.dumps(config_json))

                async with session.post(URL_TIENDA, data=data, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        return True, "Enviado con éxito."
                    else:
                        return False, f"Error del servidor de la tienda: HTTP {response.status}"
    except Exception as e:
        return False, f"No se pudo conectar con la tienda. ¿Está encendida la PC o el túnel WireGuard? ({str(e)})"


async def generar_y_enviar_reporte(update: Update, texto_periodo: str):
    """Genera resumen financiero y archivo Excel para el periodo indicado."""
    archivo_csv = "registro_impresiones.csv"
    if not os.path.exists(archivo_csv):
        await update.message.reply_text("⚠️ Aún no hay trabajos registrados en el sistema.")
        return

    df = pd.read_csv(archivo_csv)
    df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
    hoy = datetime.now().date()
    t = texto_periodo.lower()

    if "hoy" in t or "diario" in t:
        df_filtro = df[df['Fecha'] == hoy]
        periodo = "Hoy"
    elif "semana" in t:
        inicio_semana = hoy - pd.Timedelta(days=hoy.weekday())
        df_filtro = df[df['Fecha'] >= inicio_semana]
        periodo = "Esta Semana"
    elif "mes" in t:
        df_filtro = df[
            (pd.to_datetime(df['Fecha']).dt.month == hoy.month) &
            (pd.to_datetime(df['Fecha']).dt.year == hoy.year)
        ]
        periodo = "Este Mes"
    else:
        df_filtro = df
        periodo = "Histórico Completo"

    if df_filtro.empty:
        await update.message.reply_text(
            f"📊 No hay impresiones registradas para el periodo: **{periodo}**.",
            parse_mode='Markdown'
        )
        return

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
    resumen += f"- Órdenes completadas: {len(df_filtro)}\n"
    resumen += f"- Hojas utilizadas: {hojas}\n"
    resumen += f"- Impresiones B/N: {bn}\n"
    resumen += f"- Impresiones Color: {color}\n"
    resumen += f"- Fotografías Premium: {fotos}\n"

    nombre_excel = f"Reporte_{periodo.replace(' ', '_')}_{hoy}.xlsx"
    df_filtro.to_excel(nombre_excel, index=False, engine='openpyxl')

    with open(nombre_excel, 'rb') as doc:
        await update.message.reply_document(
            document=doc,
            filename=nombre_excel,
            caption=resumen,
            parse_mode='Markdown'
        )

    if os.path.exists(nombre_excel):
        os.remove(nombre_excel)


# ================= TAREAS AUTOMÁTICAS (JOBQUEUE) =================

async def tarea_mantenimiento_y_limpieza(context: ContextTypes.DEFAULT_TYPE = None):
    """Borra temporales de >24h y carpetas de órdenes de >15 días."""
    print("🧹 Iniciando limpieza automática de disco...")
    ahora = time.time()

    temp_dir = "temp_uploads"
    if os.path.exists(temp_dir):
        for archivo in os.listdir(temp_dir):
            ruta = os.path.join(temp_dir, archivo)
            if os.path.isfile(ruta) and (ahora - os.path.getmtime(ruta)) > (24 * 3600):
                os.remove(ruta)
                print(f"🗑️ Eliminado temporal caducado: {archivo}")

    if os.path.exists(BASE_DIR):
        hace_15_dias = datetime.now() - timedelta(days=15)
        for carpeta_fecha in os.listdir(BASE_DIR):
            ruta_carpeta = os.path.join(BASE_DIR, carpeta_fecha)
            if os.path.isdir(ruta_carpeta):
                try:
                    fecha_carpeta = datetime.strptime(carpeta_fecha, "%Y-%m-%d")
                    if fecha_carpeta < hace_15_dias:
                        shutil.rmtree(ruta_carpeta)
                        print(f"🗑️ Eliminado histórico caducado: {carpeta_fecha}")
                except ValueError:
                    pass


async def enviar_corte_automatico(context: ContextTypes.DEFAULT_TYPE):
    """Envía el corte diario automático a los usuarios autorizados."""
    print("📊 Ejecutando corte de caja automático...")
    archivo_csv = "registro_impresiones.csv"
    if not os.path.exists(archivo_csv):
        return

    df = pd.read_csv(archivo_csv)
    df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
    hoy = datetime.now().date()
    df_hoy = df[df['Fecha'] == hoy]

    nombre_excel = f"Corte_Diario_{hoy}.xlsx"
    if not df_hoy.empty:
        df_hoy.to_excel(nombre_excel, index=False, engine='openpyxl')

    for admin_id in USUARIOS_AUTORIZADOS:
        try:
            if df_hoy.empty:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🌙 **CORTE AUTOMÁTICO ({hoy}):**\nHoy no hubo impresiones registradas.",
                    parse_mode='Markdown'
                )
                continue

            ventas = df_hoy['Venta_Total'].sum()
            costos = df_hoy['Costo_Total'].sum()
            ganancia = df_hoy['Ganancia'].sum()
            hojas = df_hoy['Hojas_Fisicas'].sum()

            resumen = f"🌙 **CORTE DE CAJA AUTOMÁTICO: {hoy}**\n\n"
            resumen += f"💰 **Ingresos de hoy:** ${ventas:.2f} MXN\n"
            resumen += f"📉 **Gasto Insumos:** ${costos:.2f} MXN\n"
            resumen += f"✅ **GANANCIA NETA:** ${ganancia:.2f} MXN\n"
            resumen += f"📄 **Hojas gastadas:** {hojas} ({len(df_hoy)} órdenes)\n"

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

    if os.path.exists(nombre_excel):
        os.remove(nombre_excel)


# ================= HANDLERS DE TELEGRAM V2 =================

def usuario_permitido(user_id):
    return (not USUARIOS_AUTORIZADOS) or (user_id in USUARIOS_AUTORIZADOS)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not usuario_permitido(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes autorización para usar este servicio.")
        return
    teclado = [[InlineKeyboardButton("🎛️ ABRIR PANEL DE IMPRESIÓN", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        "🖨️ **Centro de Impresión Listo**\n\n"
        "1️⃣ Reenvía aquí los archivos o fotos del cliente.\n"
        "2️⃣ Toca **Abrir Panel de Impresión** para elegir acomodo y copias.\n"
        "3️⃣ Revisa el precio, la vista previa y confirma.",
        parse_mode='Markdown',
        reply_markup=TECLADO_PANEL
    )


async def cmd_limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not usuario_permitido(update.effective_user.id):
        return
    chat_id = update.message.chat_id
    if chat_id in sesiones_activas:
        for ruta in sesiones_activas[chat_id].get("archivos_temporales", []):
            if os.path.exists(ruta):
                os.remove(ruta)
        sesiones_activas.pop(chat_id, None)
    context.user_data.pop('ultima_orden', None)
    await update.message.reply_text("🗑️ Sesión limpia. Ya puedes mandar nuevos archivos.")


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not usuario_permitido(update.effective_user.id):
        return
    # Verificar ventas de hoy
    ventas_hoy = 0.0
    ordenes_hoy = 0
    if os.path.exists("registro_impresiones.csv"):
        df = pd.read_csv("registro_impresiones.csv")
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        df_hoy = df[df['Fecha'] == hoy_str]
        ventas_hoy = df_hoy['Venta_Total'].sum()
        ordenes_hoy = len(df_hoy)

    # Verificar conexión con la PC de la tienda
    base_tienda = URL_TIENDA.rsplit("/", 1)[0]
    estado_pc = "🔴 Desconectada"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_tienda, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status < 500:
                    estado_pc = "🟢 En línea (Lista para imprimir)"
    except Exception:
        pass

    await update.message.reply_text(
        f"📡 **ESTADO DEL SISTEMA**\n\n"
        f"🖥️ **PC Tienda:** {estado_pc}\n"
        f"🧾 **Órdenes hoy:** {ordenes_hoy}\n"
        f"💰 **Caja hoy:** ${ventas_hoy:.2f} MXN",
        parse_mode='Markdown'
    )


async def cmd_reporte_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if usuario_permitido(update.effective_user.id):
        await generar_y_enviar_reporte(update, "hoy")


async def cmd_reporte_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if usuario_permitido(update.effective_user.id):
        await generar_y_enviar_reporte(update, "semana")


async def cmd_reporte_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if usuario_permitido(update.effective_user.id):
        await generar_y_enviar_reporte(update, "mes")


async def cmd_reporte_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if usuario_permitido(update.effective_user.id):
        await generar_y_enviar_reporte(update, "total")


async def recibir_archivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not usuario_permitido(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes autorización para usar este servicio.")
        return

    if chat_id not in sesiones_activas:
        sesiones_activas[chat_id] = {"archivos_temporales": []}

    if update.message.document:
        archivo_tg = await update.message.document.get_file()
        extension = os.path.splitext(update.message.document.file_name)[1] or ".pdf"
    else:
        archivo_tg = await update.message.photo[-1].get_file()
        extension = ".jpg"

    os.makedirs("temp_uploads", exist_ok=True)
    ruta_tmp = os.path.join("temp_uploads", f"{uuid.uuid4()}{extension}")
    await archivo_tg.download_to_drive(ruta_tmp)
    sesiones_activas[chat_id]["archivos_temporales"].append(ruta_tmp)

    teclado = [[InlineKeyboardButton("🎛️ ABRIR PANEL DE IMPRESIÓN", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        f"📁 **{len(sesiones_activas[chat_id]['archivos_temporales'])} archivo(s) listos.**\n"
        f"Manda más o abre el panel cuando termines:",
        parse_mode='Markdown',
        reply_markup=TECLADO_PANEL
    )


async def manejar_datos_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe el JSON determinista desde la WebApp y procesa la orden sin LLM."""
    chat_id = update.message.chat_id
    if not usuario_permitido(update.effective_user.id):
        return

    data_interfaz = json.loads(update.message.web_app_data.data)

    # Soporte futuro: si la WebApp envía petición directa de reporte
    if data_interfaz.get("accion") == "reporte":
        await generar_y_enviar_reporte(update, data_interfaz.get("periodo", "hoy"))
        return

    if chat_id not in sesiones_activas or not sesiones_activas[chat_id]["archivos_temporales"]:
        await update.message.reply_text("⚠️ No tienes archivos pendientes. Manda los archivos primero.")
        return

    num_archivos = len(sesiones_activas[chat_id]["archivos_temporales"])
    config_impresion = mapear_webapp_a_config(data_interfaz, num_archivos)

    mensaje_estado = await update.message.reply_text("⚙️ Procesando documento y calculando cobro...")

    orden_id, ruta_originales, ruta_procesados = crear_carpetas_orden(chat_id)
    archivos_orden = []
    for arch_tmp in sesiones_activas[chat_id]["archivos_temporales"]:
        nueva_ruta = os.path.join(ruta_originales, os.path.basename(arch_tmp))
        os.rename(arch_tmp, nueva_ruta)
        archivos_orden.append(nueva_ruta)
    sesiones_activas.pop(chat_id, None)

    # Guardar JSON de referencia en la carpeta de la orden
    with open(os.path.join(ruta_originales, "config_webapp.json"), "w", encoding="utf-8") as f:
        json.dump(data_interfaz, f, indent=2, ensure_ascii=False)

    # Generar PDF y cotizar cobertura de tinta
    ruta_pdf_final = await unificar_y_procesar_a_pdf(archivos_orden, ruta_procesados, config_impresion)
    reporte_costos = calcular_costo_gx7110(ruta_pdf_final, config_impresion)

    # Construir desglose detallado para caja
    copias = config_impresion.get("copias", 1)
    es_doble = "Doble Cara" if config_impresion.get("doble_cara") else "1 Cara"
    tamano = config_impresion.get("tamano_papel", "carta").upper()
    tipo = config_impresion.get("tipo_papel", "normal").upper()
    rango = config_impresion.get("rango_paginas", "")
    texto_rango = "Doc. Completo" if not rango else f"Págs: {rango}"
    bandeja_pre = config_impresion.get("bandeja_manual") or "Automática"

    res = f"✅ **Orden #{orden_id} Lista**\n\n"
    res += f"⚙️ **Config:** {copias} Copias | {'Color' if config_impresion['color'] else 'B/N'} | {es_doble}\n"
    res += f"📄 **Papel:** {tamano} | {tipo} | {texto_rango}\n"
    res += f"📥 **Bandeja:** {bandeja_pre}\n\n"

    res += f"📊 **Desglose de Tinta:**\n"
    if reporte_costos['resumen_tipos']['texto_bn'] > 0:
        res += f"➖ Textos B/N: {reporte_costos['resumen_tipos']['texto_bn']} págs\n"
    if reporte_costos['resumen_tipos']['texto_color'] > 0:
        res += f"➖ Textos con color: {reporte_costos['resumen_tipos']['texto_color']} págs\n"
    if reporte_costos['resumen_tipos']['imagen_full'] > 0:
        res += f"🖼️ Full Color / Fotos: {reporte_costos['resumen_tipos']['imagen_full']} págs\n"
    res += f"📦 Hojas a consumir: {reporte_costos['hojas_fisicas_a_usar']}\n\n"

    # Alerta física de bandeja posterior para tus padres
    es_foto = config_impresion.get("tipo_papel") == "fotografico"
    es_oficio = config_impresion.get("tamano_papel") == "oficio"
    if es_foto or es_oficio:
        razon = []
        if es_oficio:
            razon.append("OFICIO")
        if es_foto:
            razon.append("FOTOGRÁFICO")
        res += f"⚠️ **PONER PAPEL {' Y '.join(razon)} EN BANDEJA POSTERIOR**\n\n"

    res += f"💰 **COBRAR AL CLIENTE: ${reporte_costos['precio_venta_sugerido']} MXN**\n"
    res += f"*(Costo: ${reporte_costos['costo_interno_mxn']} | Ganancia: ${reporte_costos['ganancia_estimada']})*"

    context.user_data['ultima_orden'] = {
        'orden_id': orden_id,
        'pdf_path': ruta_pdf_final,
        'config': config_impresion,
        'costos': reporte_costos
    }

    await mensaje_estado.delete()

    texto_btn_confirmar = (
        f"🖨️ IMPRIMIR ({config_impresion['bandeja_manual']})"
        if config_impresion.get('bandeja_manual')
        else "🖨️ ENVIAR A IMPRESORA (Automático)"
    )

    teclado = [
        [InlineKeyboardButton(texto_btn_confirmar, callback_data="print_auto")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_order")]
    ]

    with open(ruta_pdf_final, 'rb') as pdf_file:
        await update.message.reply_document(
            document=pdf_file,
            filename=f"VistaPrevia_{orden_id}.pdf",
            caption=res,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(teclado),
            read_timeout=60,
            write_timeout=60,
            connect_timeout=60
        )


async def comandos_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atajos por texto para reportes o guía rápida."""
    if not usuario_permitido(update.effective_user.id):
        return

    texto = update.message.text.lower()
    if "reporte" in texto or "corte" in texto:
        await generar_y_enviar_reporte(update, texto)
        return

    chat_id = update.message.chat_id
    if chat_id in sesiones_activas and sesiones_activas[chat_id].get("archivos_temporales"):
        teclado = [[InlineKeyboardButton("🎛️ ABRIR PANEL DE IMPRESIÓN", web_app=WebAppInfo(url=WEBAPP_URL))]]
        await update.message.reply_text(
            "👆 Ya tienes archivos cargados. Toca el botón para configurar e imprimir:",
            reply_markup=TECLADO_PANEL
        )
    else:
        await update.message.reply_text("⚠️ Envía primero las fotos o documentos del cliente.")


async def boton_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not usuario_permitido(query.from_user.id):
        await query.answer("⛔ No tienes autorización para usar este servicio.", show_alert=True)
        return

    await query.answer()

    if query.data == "cancel_order":
        context.user_data.pop('ultima_orden', None)
        await query.edit_message_caption(caption="❌ Orden cancelada en caja. No se registró cobro.")
        return

    if query.data.startswith("print_"):
        orden = context.user_data.get('ultima_orden')
        if not orden:
            await query.edit_message_caption(caption="❌ Orden caducada o ya enviada a imprimir.")
            return
        
        bandeja_final = orden['config'].get('bandeja_manual') or "Automática"
        await query.edit_message_caption(
            caption=f"✅ Confirmado (Bandeja: {bandeja_final}). 🚀 Transmitiendo a la tienda..."
        )

        # Transmisión real a FastAPI en la tienda
        exito, mensaje = await enviar_a_fastapi(orden['pdf_path'], orden['config'])

        if exito:
            guardar_registro_csv(orden['orden_id'], orden['config'], orden['costos'])
            context.user_data.pop('ultima_orden', None)
            await query.message.reply_text(
                f"🖨️ **¡Orden #{orden['orden_id']} recibida en la tienda!** Imprimiendo...",
                parse_mode='Markdown'
            )
        else:
            await query.message.reply_text(
                f"⚠️ **Falló la transmisión a la tienda:**\n{mensaje}\n\n"
                f"*(La orden NO se sumó al corte de caja)*",
                parse_mode='Markdown'
            )


async def manejador_errores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atrapa errores de red de Telegram sin detener el servicio."""
    print(f"⚠️ Hipo de conexión con Telegram ignorado: {context.error}")


# ================= INICIO DE LA APLICACIÓN =================
if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 1. Zona horaria local y tareas programadas
    tz_mexico = pytz.timezone('America/Mexico_City')
    hora_corte = dt_time(hour=22, minute=5, tzinfo=tz_mexico)
    app.job_queue.run_daily(enviar_corte_automatico, time=hora_corte)
    app.job_queue.run_once(tarea_mantenimiento_y_limpieza, 5)

    # 2. Manejador de errores
    app.add_error_handler(manejador_errores)

    # 3. Comandos rápidos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("limpiar", cmd_limpiar))
    app.add_handler(CommandHandler("estado", cmd_estado))
    app.add_handler(CommandHandler("reporte_hoy", cmd_reporte_hoy))
    app.add_handler(CommandHandler("reporte_semana", cmd_reporte_semana))
    app.add_handler(CommandHandler("reporte_mes", cmd_reporte_mes))
    app.add_handler(CommandHandler("reporte_total", cmd_reporte_total))

    # 4. Handlers principales
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, recibir_archivo))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, manejar_datos_webapp))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), comandos_texto))
    app.add_handler(CallbackQueryHandler(boton_callback, pattern="^(print_|cancel_)"))

    print("🤖 Cerebro V2 (Determinista + WebApp + Mantenimiento) iniciado...")
    app.run_polling()