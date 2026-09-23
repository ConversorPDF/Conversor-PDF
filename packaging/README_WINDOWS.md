# Taller PDF — Compilar el `.exe` para Windows

Esta guía deja **Taller PDF** convertido en una aplicación de escritorio para Windows:
un único ejecutable que arranca el servidor local y abre el navegador. Todo el
procesamiento sigue siendo **100 % local**, sin servicios externos.

> **Importante:** el `.exe` debe **compilarse en una máquina Windows**. PyInstaller genera
> binarios para el sistema operativo donde se ejecuta, así que no se puede producir un
> `.exe` desde Linux/Mac. El código ya está preparado; solo tienes que ejecutar el script.

---

## 1. Requisitos en el PC donde vas a COMPILAR

- **Windows 10/11 (64 bits).**
- **Python 3.11+** (marca *"Add Python to PATH"* al instalar).
- **Node.js 18+** y **Yarn** (`npm install -g yarn`) para construir la interfaz.

## 2. Requisitos en el PC donde se EJECUTA la app

Estas dos suites son nativas y grandes, por eso **no se empaquetan** dentro del `.exe`:
se instalan una vez en el equipo (o servidor de la red local).

| Herramienta | Para qué | Descarga oficial |
|---|---|---|
| **LibreOffice** | Word → PDF (aporta `soffice`) | https://www.libreoffice.org/download/ |
| **Ghostscript** (64-bit) | Comprimir PDF (aporta `gswin64c`) | https://www.ghostscript.com/releases/gsdnld.html |

El resto de funciones (PDF→Word, unir, dividir, imágenes→PDF) no necesitan nada más.

La app localiza `soffice` y `gswin64c` automáticamente desde el PATH o desde sus carpetas
de instalación habituales (`C:\Program Files\LibreOffice\...`, `C:\Program Files\gs\...`).
Si los instalaste en otra ruta, defínelas antes de abrir el `.exe`:

```bat
set SOFFICE_BIN=D:\Apps\LibreOffice\program\soffice.exe
set GS_BIN=D:\Apps\gs\bin\gswin64c.exe
```

## 3. Compilar (un solo paso)

Copia toda la carpeta del proyecto a Windows y ejecuta:

```bat
packaging\build_windows.bat
```

El script: construye la interfaz (`yarn build`), crea un entorno virtual de Python,
instala dependencias + PyInstaller y empaqueta la app.

Resultado:

```
backend\dist\TallerPDF\TallerPDF.exe
```

## 4. Usar / distribuir

- Doble clic en `TallerPDF.exe`: se abre una ventana de consola con la URL local
  (p. ej. `http://127.0.0.1:8501`) y el navegador se abre solo.
- Para compartirlo en la **red local**, comprime la carpeta completa `TallerPDF`
  (no solo el `.exe`, necesita los archivos que la acompañan) y cópiala a los demás
  equipos, o déjala en una carpeta compartida.
- Para que otros PCs accedan al mismo servidor por red, edita `backend/desktop.py` y
  cambia `host="127.0.0.1"` por `host="0.0.0.0"`, recompila, y abre el puerto en el
  firewall. Entonces se accede desde otro equipo con `http://IP-DEL-SERVIDOR:8501`.

## 5. Compilación manual (alternativa al `.bat`)

```bat
cd frontend
yarn install && yarn build

cd ..\backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt pyinstaller
pyinstaller ..\packaging\taller_pdf.spec --noconfirm
```

## 6. Notas

- **Sin MongoDB:** esta versión no usa base de datos; el `.exe` arranca aunque no haya
  Mongo instalado.
- **Antivirus:** los ejecutables de PyInstaller a veces disparan un falso positivo la
  primera vez. Si tu empresa firma binarios, firma `TallerPDF.exe`.
- **Tamaño:** la carpeta ronda 150–250 MB por incluir Python, FastAPI, PyMuPDF y OpenCV
  (dependencia de `pdf2docx`). Es normal.
- **Arranque en bandeja/silencioso:** si prefieres que no aparezca la consola, cambia
  `console=True` a `console=False` en `packaging/taller_pdf.spec` (perderás el mensaje
  con la URL, pero el navegador se seguirá abriendo solo).
