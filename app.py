from flask import Flask, render_template, request, jsonify, send_file
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
            numero_inventario TEXT,
            sede TEXT,
            ubicacion TEXT,
            estado TEXT
        )
    ''')
    for col in ["numero_inventario", "sede"]:
        try:
            cursor.execute(f"ALTER TABLE equipos ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/obtener-sedes', methods=['GET'])
def obtener_sedes():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT sede FROM equipos WHERE sede IS NOT NULL AND TRIM(sede) != '' ORDER BY sede ASC")
    sedes = [f[0] for f in cursor.fetchall()]
    conn.close()
    return jsonify(sedes)

@app.route('/verificar-serial/<serial>', methods=['GET'])
def verificar_serial(serial):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, marca, modelo, numero_inventario, sede, ubicacion, estado FROM equipos WHERE UPPER(serial) = UPPER(?)", (serial.strip(),))
    equipo = cursor.fetchone()
    conn.close()

    if equipo:
        return jsonify({
            "existe": True,
            "equipo": {
                "id": equipo[0],
                "nombre": equipo[1],
                "marca": equipo[2],
                "modelo": equipo[3],
                "numero_inventario": equipo[4] if equipo[4] else "",
                "sede": equipo[5] if equipo[5] else "",
                "ubicacion": equipo[6] if equipo[6] else "",
                "estado": equipo[7] if equipo[7] else "Operativo"
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
    numero_inventario = data.get('numero_inventario', '').strip()
    sede = data.get('sede', '').strip()
    ubicacion = data.get('ubicacion', '').strip()
    estado = data.get('estado', 'Operativo').strip()

    if not serial or not nombre:
        return jsonify({"status": "error", "message": "Nombre y Serial son obligatorios"}), 400

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO equipos (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Equipo registrado correctamente"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "El serial ya existe en la base de datos"}), 400

@app.route('/actualizar-equipo', methods=['POST'])
def actualizar_equipo():
    data = request.json
    serial = data.get('serial', '').strip()
    nombre = data.get('nombre', '').strip()
    marca = data.get('marca', '').strip()
    modelo = data.get('modelo', '').strip()
    numero_inventario = data.get('numero_inventario', '').strip()
    sede = data.get('sede', '').strip()
    ubicacion = data.get('ubicacion', '').strip()
    estado = data.get('estado', 'Operativo').strip()

    if not serial or not nombre:
        return jsonify({"status": "error", "message": "Nombre y Serial son obligatorios"}), 400

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE equipos 
            SET nombre = ?, marca = ?, modelo = ?, numero_inventario = ?, sede = ?, ubicacion = ?, estado = ?
            WHERE UPPER(serial) = UPPER(?)
        ''', (nombre, marca, modelo, numero_inventario, sede, ubicacion, estado, serial))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Datos del equipo actualizados correctamente"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al actualizar: {str(e)}"}), 500

@app.route('/cargar-excel', methods=['POST'])
def cargar_excel():
    if 'archivo_excel' not in request.files:
        return jsonify({"status": "error", "message": "No se adjuntó ningún archivo"}), 400
    
    file = request.files['archivo_excel']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nombre de archivo inválido"}), 400

    try:
        file_bytes = io.BytesIO(file.read())
        df_raw = pd.read_excel(file_bytes, header=None)
        
        header_row_index = None
        for idx in range(min(15, len(df_raw))):
            row_values = [str(val).strip().upper() for val in df_raw.iloc[idx].values if pd.notna(val)]
            if any('SERIE' in v or 'SERIAL' in v for v in row_values) and any('NOMBRE' in v or 'EQUIPO' in v for v in row_values):
                header_row_index = idx
                break

        if header_row_index is None:
            header_row_index = 0

        file_bytes.seek(0)
        df = pd.read_excel(file_bytes, header=header_row_index)
        df.columns = [str(c).strip().upper() for c in df.columns]

        col_serial = next((col for col in ['SERIE', 'SERIAL', 'S/N', 'NUMERO_SERIAL'] if col in df.columns), None)
        col_nombre = next((col for col in ['NOMBRE DEL EQUIPO', 'NOMBRE', 'EQUIPO', 'DESCRIPCION'] if col in df.columns), None)

        if not col_serial or not col_nombre:
            return jsonify({"status": "error", "message": "No se encontraron las columnas 'Nombre del equipo' y 'Serie' en el archivo."}), 400

        col_marca = next((col for col in ['MARCA'] if col in df.columns), None)
        col_modelo = next((col for col in ['MODELO'] if col in df.columns), None)
        col_inv = next((col for col in ['NO. INVENTARIO', 'NO INVENTARIO', 'INVENTARIO', 'ACTIVO FIJO', 'NUMERO DE SAP', 'CODIGO'] if col in df.columns), None)
        col_sede = next((col for col in ['SEDE', 'UNIDAD DE NEGOCIO', 'CENTRO DE COSTO'] if col in df.columns), None)
        col_ubicacion = next((col for col in ['UBICACIÓN ESPECIFICA', 'UBICACION ESPECIFICA', 'UBICACION'] if col in df.columns), None)
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
            num_inv = str(row[col_inv]).strip() if col_inv and pd.notna(row[col_inv]) else ""
            sede = str(row[col_sede]).strip() if col_sede and pd.notna(row[col_sede]) else ""
            ubicacion = str(row[col_ubicacion]).strip() if col_ubicacion and pd.notna(row[col_ubicacion]) else ""
            estado = str(row[col_estado]).strip() if col_estado and pd.notna(row[col_estado]) else "Operativo"

            try:
                cursor.execute('''
                    INSERT INTO equipos (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (nombre, marca, modelo, serial, num_inv, sede, ubicacion, estado))
                agregados += 1
            except sqlite3.IntegrityError:
                omitidos_duplicados += 1

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": f"Carga completada. Equipos nuevos registrados: {agregados}. Equipos omitidos (serial duplicado): {omitidos_duplicados}."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error procesando Excel: {str(e)}"}), 500

@app.route('/limpiar-bd', methods=['POST'])
def limpiar_bd():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM equipos')
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Base de datos vaciada por completo."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al reiniciar BD: {str(e)}"}), 500

@app.route('/listar-equipos', methods=['GET'])
def listar_equipos():
    query = request.args.get('q', '').strip()
    filter_sede = request.args.get('sede', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    sql = 'SELECT id, nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado FROM equipos WHERE 1=1'
    params = []

    if filter_sede:
        sql += ' AND UPPER(sede) = UPPER(?)'
        params.append(filter_sede)

    if query:
        search_pattern = f"%{query}%"
        sql += ' AND (nombre LIKE ? OR serial LIKE ? OR numero_inventario LIKE ? OR marca LIKE ? OR ubicacion LIKE ?)'
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

    sql += ' ORDER BY id DESC LIMIT 200'

    cursor.execute(sql, params)
    filas = cursor.fetchall()
    conn.close()

    equipos = [{
        "id": f[0], "nombre": f[1], "marca": f[2], "modelo": f[3],
        "serial": f[4], "numero_inventario": f[5], "sede": f[6], "ubicacion": f[7], "estado": f[8]
    } for f in filas]

    return jsonify(equipos)

@app.route('/descargar-excel', methods=['GET'])
def descargar_excel():
    filter_sede = request.args.get('sede', '').strip()
    conn = sqlite3.connect(DB_NAME)
    
    if filter_sede:
        query = '''
            SELECT id AS ID, nombre AS NOMBRE, marca AS MARCA, modelo AS MODELO, 
                   serial AS SERIAL, numero_inventario AS "NO. INVENTARIO", 
                   sede AS SEDE, ubicacion AS UBICACION, estado AS ESTADO 
            FROM equipos WHERE UPPER(sede) = UPPER(?)
        '''
        df = pd.read_sql_query(query, conn, params=(filter_sede,))
    else:
        query = '''
            SELECT id AS ID, nombre AS NOMBRE, marca AS MARCA, modelo AS MODELO, 
                   serial AS SERIAL, numero_inventario AS "NO. INVENTARIO", 
                   sede AS SEDE, ubicacion AS UBICACION, estado AS ESTADO 
            FROM equipos
        '''
        df = pd.read_sql_query(query, conn)
        
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario_General')
    
    output.seek(0)
    filename = f"Inventario_{filter_sede.replace(' ', '_')}.xlsx" if filter_sede else "Inventario_Biomedico_Actualizado.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
