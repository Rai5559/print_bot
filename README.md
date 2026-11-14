# 🖨️ PrintBot AI — Sistema Distribuido de Automatización para Centro de Copiado (v1.0)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Llama_3.1_8B-000000?style=for-the-badge)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)
![WireGuard](https://img.shields.io/badge/WireGuard_VPN-88171A?style=for-the-badge&logo=wireguard&logoColor=white)

**PrintBot AI** es un sistema inteligente de punto de venta, maquetación automática y despacho remoto de impresiones controlado por **lenguaje natural a través de Telegram**. 

Diseñado bajo una arquitectura distribuida **Cerebro + Músculo**, permite procesar documentos pesados, limpiar fotografías tomadas con celular, armar planillas milimétricas, calcular costos exactos por cobertura real de tinta pixel por pixel y enviar trabajos directamente a las bandejas físicas de una impresora **Canon MAXIFY GX7110** a través de un túnel seguro VPN.

---

## 🏗️ Arquitectura del Sistema

```text
[ 📱 Telegram (Mostrador / Cliente) ]
                 │
                 ▼ (Archivos + Instrucción en Lenguaje Natural)
┌─────────────────────────────────────────────────────────────────────────┐
│ 🧠 NODO CEREBRO (PC Principal - RTX 5070 Ti + Ryzen 7 7800X3D)          │
│  ├─ Ollama (Llama 3.1:8b): Extrae parámetros e intenciones a JSON       │
│  ├─ Motor de 5 Carriles: Pillow / OpenCV / Rectpack / Playwright        │
│  ├─ Cotizador Numpy: Analiza % de cobertura RGB y B/N por página        │
│  └─ Base de Datos & Jobs: Registro CSV, Excel con Pandas y Auto-Limpieza│
└─────────────────────────────────────────────────────────────────────────┘
                 │
                 ▼ (Túnel Privado WireGuard VPN - HTTP POST)
┌─────────────────────────────────────────────────────────────────────────┐
│ 💪 NODO MÚSCULO (ThinkPad en Tienda Local)                              │
│  ├─ FastAPI (api_tienda.py): Recibe PDF procesado + JSON de bandeja     │
│  └─ SumatraPDF CLI: Despacho silencioso a Canon MAXIFY GX7110           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Características Principales (v1.0)

### 🛣️ Motor de Renderizado Híbrido de 5 Carriles
El sistema evalúa cada pedido y decide automáticamente qué motor gráfico utilizar:
1. **Carril 1 — Diseños Asimétricos Web (`Playwright` + `HTML/CSS`):** Para pedidos como *"pon la primera foto grande arriba y las otras dos pequeñas abajo"*. Incluye cortafuegos de red, sanitización anti-scripts y soporte para papel Carta/Oficio en vertical u horizontal.
2. **Carril 2 — Modo Planilla Exacta (`Pillow`):** Genera planillas de fotos tamaño Infantil ($2.5 \times 3.0\text{ cm}$), Pasaporte ($3.5 \times 4.5\text{ cm}$) o medidas personalizadas (ej. $5 \times 5\text{ cm}$) con anclaje *Top-Left* para ahorrar papel y facilitar el corte con tijera.
3. **Carril 3 — Cuadrículas Inteligentes (`N-Up`):** Agrupa $N$ archivos distintos en una sola hoja calculando automáticamente la rotación y el empaquetado óptimo.
4. **Carril 4 — Modo Tetris Matemático (`rectpack` Bin Packing):** Mantiene el tamaño original de múltiples recortes o imágenes asimétricas y juega "Tetris" rotándolas a $90^\circ$ para lograr el mínimo desperdicio de papel.
5. **Carril 5 — Modo Escáner y Credenciales (`OpenCV` + `ImageOps`):**
   * **Modo INE Automático:** Endereza fotos verticales, iguala proporciones con relleno blanco (`ImageOps.pad` a $8.5 \times 5.4\text{ cm}$), aplica autocontraste + $20\%$ de brillo para eliminar el fondo gris y permite escalas al $50\%$ o $200\%$.
   * **Filtro Anti-Sombras (`OpenCV`):** Utiliza umbralización adaptativa Gaussiana (`adaptiveThreshold`) para transformar fotos oscuras de actas o recibos en documentos con fondo blanco puro (`#FFFFFF`), ahorrando hasta un $60\%$ de tinta negra.

### 🧮 Cotizador Dinámico de Tinta (Numpy)
A diferencia de los sistemas tradicionales que cobran por hoja fija, PrintBot renderiza cada página a $72\text{ DPI}$ en memoria y utiliza matrices de **Numpy** para medir la mancha real de tinta:
* **Páginas B/N o color imperceptible ($\le 1\%$):** Tarifa base económica.
* **Documentos con títulos/gráficas a color ($1\% - 15\%$):** Tarifa intermedia.
* **Imágenes Full Color / Cobertura pesada ($> 15\%$):** Tarifa completa.
* **Papel Fotográfico (Glossy):** Tarifa premium con desvío automático a la Bandeja Posterior.

### ✂️ Impresión Parcial Blindada (Regex)
Soporta extracción de rangos complejos (ej. *"imprime solo de la 13 a la 23 y 45-50"*) directamente en memoria con `PyMuPDF` antes de renderizar, ahorrando RAM y cotizando únicamente las páginas solicitadas.

### 📊 Contabilidad Automática y Mantenimiento Autónomo
* **Registro Transaccional:** Guarda cada orden confirmada e impresa en `registro_impresiones.csv` (ignora órdenes canceladas).
* **Reportes en Excel bajo demanda:** Genera archivos `.xlsx` detallados filtrados por día, semana, mes o histórico completo.
* **Corte de Caja Nocturno (`JobQueue`):** Envía automáticamente a las **10:05 PM** (hora CDMX) el corte financiero del día a los administradores autorizados.
* **Recolector de Basura:** Al iniciar el bot, purga archivos temporales abandonados ($>24\text{ horas}$) y carpetas históricas de clientes ($>15\text{ días}$).

---

## 📂 Estructura Recomendada del Repositorio

Al unificar ambas carpetas (Cerebro y Tienda), organiza tu proyecto de la siguiente manera:

```text
print_bot/
├── cerebro/
│   ├── main.py                # Bot de Telegram, IA, Visión y Cotizador
│   ├── simulador_v2.py        # Entorno Sandbox de pruebas (11 tests)
│   └── requirements.txt       # Librerías del nodo Cerebro
├── tienda/
│   ├── api_tienda.py          # Servidor FastAPI + SumatraPDF
│   └── requirements.txt       # Librerías del nodo Músculo (ThinkPad)
├── .env.example               # Plantilla de variables de entorno (Sin datos reales)
├── .gitignore                 # Reglas para ocultar .env y archivos de clientes
└── README.md                  # Este documento
```

---

## ⚙️ Instalación y Configuración

### 1. Requisitos Previos
* **Nodo Cerebro:** Python 3.11+, [Ollama](https://ollama.com/) instalado con el modelo `llama3.1:8b` (`ollama pull llama3.1:8b`), y Microsoft Word instalado (requerido por `docx2pdf`).
* **Nodo Tienda:** Python 3.11+, [SumatraPDF](https://www.sumatrapdfreader.org/) (ejecutable portable o instalado) y drivers de la impresora Canon MAXIFY GX7110.
* **Red:** Túnel activo en **WireGuard** conectando ambas máquinas.

### 2. Instalación en el Nodo Cerebro
```bash
cd cerebro
python -m venv venv
.\venv\Scripts\activate

pip install python-telegram-bot[job-queue] ollama pymupdf pillow python-dotenv aiohttp docx2pdf numpy pandas openpyxl playwright rectpack opencv-python pytz

# Descargar el motor Chromium oculto para el Carril HTML
python -m playwright install chromium
```

### 3. Optimización de VRAM para Gaming (`OLLAMA_KEEP_ALIVE`)
Para evitar que Llama 3.1 ocupe $6\text{ GB}$ de VRAM en la tarjeta gráfica mientras no hay pedidos (permitiendo jugar títulos pesados sin tirones):
1. Abre las **Variables de entorno del sistema** en Windows.
2. Crea una nueva variable de sistema:
   * **Nombre:** `OLLAMA_KEEP_ALIVE`
   * **Valor:** `0`
3. Reinicia Ollama. El modelo se cargará en $1\text{ segundo}$ al recibir una orden y liberará la VRAM inmediatamente después.

### 4. Variables de Entorno (`.env`)
Crea un archivo llamado `.env` dentro de la carpeta `cerebro/` basándote en `.env.example`:
```env
TELEGRAM_BOT=1234567890:AAH_TU_TOKEN_SECRETO_DE_BOTFATHER
USUARIOS_AUTORIZADOS=111222333,444555666
```

---

## 📱 Guía Rápida de Comandos en Telegram (Mostrador)

> **Regla de Oro:** Primero envía todos los archivos o fotos al bot. Espera a que responda *"📁 Archivo recibido"* y luego escribe cómo los quieres en lenguaje natural.

| Necesidad del Cliente | Ejemplo de Instrucción en Telegram |
| :--- | :--- |
| **Impresión Básica / Copias** | *"Sácame 3 copias a color por ambos lados"* |
| **Cambio de Papel** | *"Imprime esto en tamaño oficio"* o *"En papel fotográfico sin bordes"* |
| **Credencial INE / IFE** | *"Copia de este INE"* o *"Copia de credencial al 200%"* |
| **Recibos Oscuros / Con Sombra** | *"Imprime este recibo en modo escáner"* o *"Aclarar fondo"* |
| **Fotos Infantiles / Planillas** | *"Ponme 6 fotos tamaño infantil"* o *"Lléname la hoja de fotos pasaporte"* |
| **Medidas Exactas en cm** | *"Sácame 2 hojas con 5 fotos de 5x5 a color cada una"* |
| **Agrupar en Cuadrícula** | *"Pon las 3 imágenes en la misma hoja a color"* |
| **Diseño Asimétrico (HTML)** | *"Pon la primera foto grande arriba y las otras dos pequeñas abajo"* |
| **Ahorro Máximo (Modo Tetris)** | *"Acomoda todas estas fotos como quepan sin desperdiciar papel"* |
| **Impresión Parcial de PDF** | *"Imprime a color solo de la 13 a la 23 y 45-50"* |
| **Cortes de Caja (Sin archivos)** | *"Mándame el reporte de hoy"*, *"Reporte de la semana"* o *"Reporte del mes"* |

---

## 🧪 Entorno de Pruebas (Sandbox)

Antes de pasar cambios a producción, puedes ejecutar el simulador incluido para validar los 11 módulos (Cuadrículas, INE, Planillas, Regex, Tetris, HTML blindado, OpenCV y Excel) sin usar Telegram ni gastar tinta:

```bash
python simulador_v2.py
```
Los resultados visuales se generarán automáticamente en la carpeta `PRUEBAS_SISTEMA_V2/`.