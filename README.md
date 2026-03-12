# Bank Statement Parser

Aplicacion para extraer transacciones de estados de cuenta BBVA y Santander, validar totales y exportar resultados a CSV o Excel.

## Stack

- Python
- PyMuPDF
- pandas
- openpyxl
- Streamlit

## Ejecutar en local

1. Crea y activa tu entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Lanza la interfaz:

```bash
streamlit run app.py
```

4. O usa la CLI actual:

```bash
python main.py --bank bbva --pdf "sample_pdfs/02.BBVA_Estado de cuenta_0255 ByF Capital MXN 2026.pdf"
```

## Estructura

- `app.py`: interfaz Streamlit.
- `main.py`: ejecucion por linea de comandos.
- `parsers/bbva.py`: parser BBVA.
- `parsers/santander.py`: parser Santander.
- `core/exporter.py`: exportacion a CSV y Excel.

## Subir a GitHub

```bash
git init
git add .
git commit -m "Initial Streamlit app"
git branch -M main
git remote add origin <TU_REPO_GITHUB>
git push -u origin main
```

## Deploy en Streamlit Community Cloud

1. Sube el repo a GitHub.
2. Entra a [Streamlit Community Cloud](https://share.streamlit.io/).
3. Crea una app nueva conectando tu repositorio.
4. Usa estos valores:

- Repository: tu repo en GitHub
- Branch: `main`
- Main file path: `app.py`

Streamlit instalara automaticamente lo que encuentre en `requirements.txt`.
