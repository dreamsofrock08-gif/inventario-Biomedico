from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
import pandas as pd
import io

app = Flask(__name__)
CORS(app)
DB_NAME = "inventario.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            marca TEXT,
            modelo TEXT,
            serial TEXT UNIQUE NOT NULL,
            ubicacion TEXT,
            estado TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/verificar-serial/<serial>', methods=['GET'])
def verificar_serial(serial):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, marca, modelo, ubicacion FROM equipos WHERE UPPER(serial) = UPPER(?)", (serial.strip(),))
    equipo = cursor.fetchone()
    conn.close()

    if equipo:
        return jsonify({
            "existe": True,
            "equipo": {
                "nombre": equipo[1],
                "marca": equipo[2],
                "modelo": equipo[3],
                "ubicacion": equipo[4]
            }
        })
    return jsonify({"existe": False})

@app.route('/agregar-equipo', methods=['POST'])
def agregar_equipo():
    data = request.json
    serial = data.get('serial', '').strip()
    nombre = data.get('nombre', '').strip()
    marca = data.get('marca', '').strip()
    modelo = data.get('modelo', '').strip()
    ubicacion = data.get('ubicacion', '').strip()
    estado = data.get('estado', 'Operativo').strip()

    if not serial or not nombre:
        return jsonify({"status": "error", "message": "Nombre y Serial son obligatorios"}), 400

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO equipos (nombre, marca, modelo, serial, ubicacion, estado)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nombre, marca, modelo, serial, ubicacion, estado))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Equipo registrado correctamente"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "El serial ya existe en la base de datos"}), 400

@app.route('/cargar-excel', methods=['POST'])
def cargar_excel():
    if 'archivo_excel' not in request.files:
        return jsonify({"status": "error", "message": "No se adjuntó ningún archivo"}), 400
    
    file = request.files['archivo_excel']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nombre de archivo inválido"}), 400

    try:
        file_bytes = io.BytesIO(file.read())
        
        # Leer las primeras 15 filas sin encabezado para buscar la fila de nombres de columna real
        df_raw = pd.read_excel(file_bytes, header=None)
        
        header_row_index = None
        for idx in range(min(15, len(df_raw))):
            row_values = [str(val).strip().upper() for val in df_raw.iloc[idx].values if pd.notna(val)]
            if any('SERIE' in v or 'SERIAL' in v for v in row_values) and any('NOMBRE' in v or 'EQUIPO' in v for v in row_values):
                header_row_index = idx
                break

        if header_row_index is None:
            header_row_index = 0  # Caer de respaldo en la fila 0 si no se detecta la fila

        # Volver al inicio del stream para re-leer con el encabezado correcto
        file_bytes.seek(0)
        df = pd.read_excel(file_bytes, header=header_row_index)

        # Normalizar nombres de columnas a mayúsculas
        df.columns = [str(c).strip().upper() for c in df.columns]

        # Mapear variaciones comunes de encabezados en el formato PMP
        columnas_posibles_serial = ['SERIE', 'SERIAL', 'NO. INVENTARIO', 'S/N', 'NUMERO_SERIAL']
        col_serial = next((col for col in columnas_posibles_serial if col in df.columns), None)

        columnas_posibles_nombre = ['NOMBRE DEL EQUIPO', 'NOMBRE', 'EQUIPO', 'DESCRIPCION']
        col_nombre = next((col for col in columnas_posibles_nombre if col in df.columns), None)

        if not col_serial or not col_nombre:
            return jsonify({
                "status": "error", 
                "message": "No se encontraron las columnas 'Nombre del equipo' y 'Serie' en el archivo."
            }), 400

        col_marca = next((col for col in ['MARCA'] if col in df.columns), None)
        col_modelo = next((col for col in ['MODELO'] if col in df.columns), None)
        col_ubicacion = next((col for col in ['UBICACIÓN ESPECIFICA', 'UBICACION ESPECIFICA', 'UBICACION', 'SEDE'] if col in df.columns), None)
        col_estado = next((col for col in ['ESTADO', 'TIPO DE INTERVENCIÓN', 'TIPO DE INTERVENCION'] if col in df.columns), None)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        agregados = 0
        omitidos_duplicados = 0

        for _, row in df.iterrows():
            serial = str(row[col_serial]).strip() if pd.notna(row[col_serial]) else ""
            nombre = str(row[col_nombre]).strip() if pd.notna(row[col_nombre]) else ""

            if not serial or not nombre or serial.upper() in ['NAN', 'NONE', 'NO APLICA', 'SIN SERIE']:
                continue

            marca = str(row[col_marca]).strip() if col_marca and pd.notna(row[col_marca]) else ""
            modelo = str(row[col_modelo]).strip() if col_modelo and pd.notna(row[col_modelo]) else ""
            ubicacion = str(row[col_ubicacion]).strip() if col_ubicacion and pd.notna(row[col_ubicacion]) else ""
            estado = str(row[col_estado]).strip() if col_estado and pd.notna(row[col_estado]) else "Operativo"

            try:
                cursor.execute('''
                    INSERT INTO equipos (nombre, marca, modelo, serial, ubicacion, estado)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (nombre, marca, modelo, serial, ubicacion, estado))
                agregados += 1
            except sqlite3.IntegrityError:
                omitidos_duplicados += 1

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": f" Carga completada. Equipos nuevos registrados: {agregados}. Equipos omitidos (serial duplicado): {omitidos_duplicados}."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error procesando Excel: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
