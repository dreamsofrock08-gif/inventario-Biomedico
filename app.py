from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import pandas as pd
import io

app = Flask(__name__)
CORS(app)
DB_NAME = "inventario.db"

MESES_ORDEN = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE']
MES_ACTUAL_IDX = 8  # Considerando Octubre (índice 9 en año completo, Septiembre consumido)

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
            estado TEXT,
            frecuencia_pmp TEXT,
            meses_programados TEXT,
            ultimo_mantenimiento TEXT,
            aplazado TEXT,
            cumplimiento_pmp TEXT
        )
    ''')
    
    columnas_nuevas = ["numero_inventario", "sede", "frecuencia_pmp", "meses_programados", "ultimo_mantenimiento", "aplazado", "cumplimiento_pmp"]
    for col in columnas_nuevas:
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

@app.route('/datos-dashboard', methods=['GET'])
def datos_dashboard():
    """Calcula estadísticas gerenciales dividiendo ejecutados, en mora, aplazados y programados a futuro."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM equipos")
    total_equipos = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM equipos WHERE UPPER(cumplimiento_pmp) LIKE '%AL DIA%' OR UPPER(cumplimiento_pmp) LIKE '%AL DÍA%'")
    total_al_dia = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM equipos WHERE UPPER(cumplimiento_pmp) LIKE '%EN MORA%'")
    total_en_mora = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM equipos WHERE UPPER(aplazado) LIKE '%SÍ%' OR UPPER(aplazado) LIKE '%SI%' OR UPPER(cumplimiento_pmp) LIKE '%APLAZADO%'")
    total_aplazados = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM equipos WHERE UPPER(cumplimiento_pmp) LIKE '%PROGRAMADO%' OR UPPER(cumplimiento_pmp) LIKE '%FUTURO%'")
    total_futuros = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM equipos WHERE UPPER(estado) LIKE '%FUERA DE SERVICIO%'")
    total_fuera_servicio = cursor.fetchone()[0]

    # Estadísticas desglosadas por Sede
    cursor.execute('''
        SELECT sede, 
               SUM(CASE WHEN UPPER(cumplimiento_pmp) LIKE '%AL D%' THEN 1 ELSE 0 END) as al_dia,
               SUM(CASE WHEN UPPER(cumplimiento_pmp) LIKE '%EN MORA%' THEN 1 ELSE 0 END) as en_mora,
               SUM(CASE WHEN UPPER(cumplimiento_pmp) LIKE '%PROGRAMADO%' OR UPPER(cumplimiento_pmp) LIKE '%FUTURO%' THEN 1 ELSE 0 END) as futuros,
               SUM(CASE WHEN UPPER(estado) LIKE '%FUERA DE SERVICIO%' THEN 1 ELSE 0 END) as fuera_servicio
        FROM equipos 
        WHERE sede IS NOT NULL AND TRIM(sede) != ''
        GROUP BY sede
        ORDER BY en_mora DESC, COUNT(*) DESC
    ''')
    sedes_data = cursor.fetchall()

    conn.close()

    porcentaje_cumplimiento = round((total_al_dia / total_equipos * 100), 1) if total_equipos > 0 else 0

    return jsonify({
        "total_equipos": total_equipos,
        "total_al_dia": total_al_dia,
        "total_en_mora": total_en_mora,
        "total_aplazados": total_aplazados,
        "total_futuros": total_futuros,
        "total_fuera_servicio": total_fuera_servicio,
        "porcentaje_cumplimiento": porcentaje_cumplimiento,
        "sedes_stats": [{
            "sede": s[0], "al_dia": s[1], "en_mora": s[2], "futuros": s[3], "fuera_servicio": s[4]
        } for s in sedes_data]
    })

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
    cursor.execute('''
        SELECT id, nombre, marca, modelo, numero_inventario, sede, ubicacion, estado, 
               frecuencia_pmp, meses_programados, ultimo_mantenimiento, aplazado, cumplimiento_pmp 
        FROM equipos WHERE UPPER(serial) = UPPER(?)
    ''', (serial.strip(),))
    equipo = cursor.fetchone()
    conn.close()

    if equipo:
        return jsonify({
            "existe": True,
            "equipo": {
                "id": equipo[0], "nombre": equipo[1], "marca": equipo[2], "modelo": equipo[3],
                "numero_inventario": equipo[4] if equipo[4] else "",
                "sede": equipo[5] if equipo[5] else "",
                "ubicacion": equipo[6] if equipo[6] else "",
                "estado": equipo[7] if equipo[7] else "Operativo",
                "frecuencia_pmp": equipo[8] if equipo[8] else "No especificada",
                "meses_programados": equipo[9] if equipo[9] else "No especificado",
                "ultimo_mantenimiento": equipo[10] if equipo[10] else "Sin registro OK",
                "aplazado": equipo[11] if equipo[11] else "No",
                "cumplimiento_pmp": equipo[12] if equipo[12] else "Pendiente"
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

    if not all([serial, nombre, marca, modelo, numero_inventario, sede, ubicacion, estado]):
        return jsonify({"status": "error", "message": "Todos los campos obligatorios deben estar diligenciados"}), 400

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO equipos (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado, cumplimiento_pmp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Al Dia')
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

    if not all([serial, nombre, marca, modelo, numero_inventario, sede, ubicacion, estado]):
        return jsonify({"status": "error", "message": "Todos los campos obligatorios deben estar diligenciados"}), 400

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
        
        header_row_index = 3
        for idx in range(min(15, len(df_raw))):
            row_values = [str(val).strip().upper() for val in df_raw.iloc[idx].values if pd.notna(val)]
            if any('SERIE' in v or 'SERIAL' in v for v in row_values) and any('NOMBRE' in v or 'EQUIPO' in v for v in row_values):
                header_row_index = idx
                break

        meses_cols = {}
        curr_mes = None
        for col_idx in range(25, min(80, df_raw.shape[1])):
            val_f2 = str(df_raw.iloc[2, col_idx]).strip().upper() if len(df_raw) > 2 else ""
            if val_f2 in MESES_ORDEN:
                curr_mes = val_f2
            if curr_mes:
                if curr_mes not in meses_cols:
                    meses_cols[curr_mes] = []
                meses_cols[curr_mes].append(col_idx)

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
        col_frec = next((col for col in ['FRECUENCIA'] if col in df.columns), None)
        col_meses = next((col for col in ['MESES', 'MESES '] if col in df.columns), None)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        agregados = 0
        omitidos_duplicados = 0

        for r_idx, row in df.iterrows():
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
            frecuencia = str(row[col_frec]).strip() if col_frec and pd.notna(row[col_frec]) else ""
            meses_prog = str(row[col_meses]).strip() if col_meses and pd.notna(row[col_meses]) else ""

            row_raw_idx = r_idx + header_row_index + 1
            ult_ok = "Ninguno"
            hubo_aplazamiento = "No"
            tiene_mora_pasada = False
            tiene_programado_futuro = False

            if row_raw_idx < len(df_raw):
                for m_idx, m_nombre in enumerate(MESES_ORDEN):
                    if m_nombre in meses_cols:
                        cols_m = meses_cols[m_nombre]
                        vals = [str(df_raw.iloc[row_raw_idx, c]).strip().upper() for c in cols_m if c < df_raw.shape[1] and pd.notna(df_raw.iloc[row_raw_idx, c])]
                        
                        if 'OK' in vals:
                            ult_ok = m_nombre
                        if any(v in ['IF', 'R', 'REPROGRAMADO', 'APLAZADO'] for v in vals):
                            hubo_aplazamiento = "Sí"
                        
                        if 'PG' in vals:
                            if m_idx <= MES_ACTUAL_IDX:
                                tiene_mora_pasada = True
                            else:
                                tiene_programado_futuro = True

            if tiene_mora_pasada:
                cumplimiento = "En Mora"
            elif hubo_aplazamiento == "Sí":
                cumplimiento = "Aplazado"
            elif ult_ok != "Ninguno":
                cumplimiento = "Al Dia"
            elif tiene_programado_futuro:
                cumplimiento = "Programado Futuro"
            else:
                cumplimiento = "Al Dia"

            try:
                cursor.execute('''
                    INSERT INTO equipos (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado, 
                                        frecuencia_pmp, meses_programados, ultimo_mantenimiento, aplazado, cumplimiento_pmp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (nombre, marca, modelo, serial, num_inv, sede, ubicacion, estado, frecuencia, meses_prog, ult_ok, hubo_aplazamiento, cumplimiento))
                agregados += 1
            except sqlite3.IntegrityError:
                omitidos_duplicados += 1

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": f"Carga completada. Equipos procesados con auditoría PMP: {agregados}. Duplicados omitidos: {omitidos_duplicados}."
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
    filter_cumplimiento = request.args.get('cumplimiento', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    sql = '''SELECT id, nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado, 
                    frecuencia_pmp, meses_programados, ultimo_mantenimiento, aplazado, cumplimiento_pmp 
             FROM equipos WHERE 1=1'''
    params = []

    if filter_sede:
        sql += ' AND UPPER(sede) = UPPER(?)'
        params.append(filter_sede)

    if filter_cumplimiento:
        sql += ' AND (UPPER(cumplimiento_pmp) LIKE UPPER(?) OR UPPER(cumplimiento_pmp) LIKE UPPER(?))'
        params.extend([f"%{filter_cumplimiento}%", f"%{filter_cumplimiento.replace('Día', 'Dia')}%"])

    if query:
        search_pattern = f"%{query}%"
        sql += ' AND (nombre LIKE ? OR serial LIKE ? OR numero_inventario LIKE ? OR marca LIKE ? OR ubicacion LIKE ?)'
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

    sql += ' ORDER BY id DESC LIMIT 200'

    cursor.execute(sql, params)
    filas = cursor.fetchall()
    conn.close()

    equipos = [{
        "id": f[0], "nombre": f[1], "marca": f[2], "modelo": f[3], "serial": f[4], 
        "numero_inventario": f[5], "sede": f[6], "ubicacion": f[7], "estado": f[8],
        "frecuencia_pmp": f[9], "meses_programados": f[10], "ultimo_mantenimiento": f[11],
        "aplazado": f[12], "cumplimiento_pmp": f[13]
    } for f in filas]

    return jsonify(equipos)

@app.route('/descargar-excel', methods=['GET'])
def descargar_excel():
    filter_sede = request.args.get('sede', '').strip()
    filter_cumplimiento = request.args.get('cumplimiento', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    sql = '''
        SELECT id AS ID, nombre AS NOMBRE, marca AS MARCA, modelo AS MODELO, 
               serial AS SERIAL, numero_inventario AS "NO. INVENTARIO", 
               sede AS SEDE, ubicacion AS UBICACION, estado AS ESTADO,
               frecuencia_pmp AS "FRECUENCIA PMP", meses_programados AS "MESES PROGRAMADOS",
               ultimo_mantenimiento AS "ULTIMO MANTENIMIENTO (OK)",
               aplazado AS "HUBO APLAZAMIENTO", cumplimiento_pmp AS "CUMPLIMIENTO PMP"
        FROM equipos WHERE 1=1
    '''
    params = []

    if filter_sede:
        sql += ' AND UPPER(sede) = UPPER(?)'
        params.append(filter_sede)

    if filter_cumplimiento:
        sql += ' AND UPPER(cumplimiento_pmp) LIKE UPPER(?)'
        params.append(f"%{filter_cumplimiento}%")

    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario_General')
    
    output.seek(0)
    filename = f"Inventario_{filter_sede if filter_sede else 'General'}.xlsx".replace(' ', '_')
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
