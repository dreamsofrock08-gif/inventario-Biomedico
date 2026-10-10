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
            estado TEXT,
            frecuencia_pmp TEXT,
            meses_programados TEXT,
            ultimo_mantenimiento TEXT,
            aplazado TEXT,
            cumplimiento_pmp TEXT,
            observacion TEXT
        )
    ''')
    
    columnas = ["numero_inventario", "sede", "frecuencia_pmp", "meses_programados", "ultimo_mantenimiento", "aplazado", "cumplimiento_pmp", "observacion"]
    for col in columnas:
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
    """Retorna las estadísticas del Dashboard EXCLUYENDO 'NO APLICA' y 'BAJA', filtrables por Sede."""
    filter_sede = request.args.get('sede', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    sql_where = " WHERE UPPER(cumplimiento_pmp) NOT IN ('NO APLICA', 'BAJA')"
    params = []

    if filter_sede:
        sql_where += " AND UPPER(sede) = UPPER(?)"
        params.append(filter_sede)

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where}", params)
    total_equipos_pmp = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where} AND UPPER(cumplimiento_pmp) = 'REALIZADO'", params)
    total_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where} AND UPPER(cumplimiento_pmp) = 'NO REALIZADO'", params)
    total_no_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where} AND UPPER(cumplimiento_pmp) = 'A FUTURO'", params)
    total_a_futuro = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where} AND UPPER(estado) = 'FUERA DE SERVICIO'", params)
    total_fuera_servicio = cursor.fetchone()[0]

    # Agrupar por la columna de observaciones del final (Columna 84)
    sql_razones = f'''
        SELECT COALESCE(NULLIF(TRIM(observacion), ''), 'Sin observación registrada') as razon, COUNT(*) 
        FROM equipos 
        {sql_where} AND UPPER(cumplimiento_pmp) = 'NO REALIZADO'
        GROUP BY razon
        ORDER BY COUNT(*) DESC
    '''
    cursor.execute(sql_razones, params)
    razones_no_realizado = [{"razon": row[0], "cantidad": row[1]} for row in cursor.fetchall()]

    # Gráfico general de sedes
    cursor.execute('''
        SELECT sede, 
               SUM(CASE WHEN UPPER(cumplimiento_pmp) = 'REALIZADO' THEN 1 ELSE 0 END) as realizado,
               SUM(CASE WHEN UPPER(cumplimiento_pmp) = 'NO REALIZADO' THEN 1 ELSE 0 END) as no_realizado,
               SUM(CASE WHEN UPPER(cumplimiento_pmp) = 'A FUTURO' THEN 1 ELSE 0 END) as a_futuro
        FROM equipos 
        WHERE sede IS NOT NULL AND TRIM(sede) != '' AND UPPER(cumplimiento_pmp) NOT IN ('NO APLICA', 'BAJA')
        GROUP BY sede
        ORDER BY no_realizado DESC, COUNT(*) DESC
    ''')
    sedes_data = cursor.fetchall()

    conn.close()

    porcentaje_cumplimiento = round((total_realizado / total_equipos_pmp * 100), 1) if total_equipos_pmp > 0 else 0

    return jsonify({
        "total_equipos_pmp": total_equipos_pmp,
        "total_realizado": total_realizado,
        "total_no_realizado": total_no_realizado,
        "total_a_futuro": total_a_futuro,
        "total_fuera_servicio": total_fuera_servicio,
        "porcentaje_cumplimiento": porcentaje_cumplimiento,
        "razones_no_realizado": razones_no_realizado,
        "sedes_stats": [{
            "sede": s[0], "realizado": s[1], "no_realizado": s[2], "a_futuro": s[3]
        } for s in sedes_data]
    })

@app.route('/generar-informe-ejecutivo', methods=['GET'])
def generar_informe_ejecutivo():
    """Genera la conciliación completa entre Inventario Total y Plan PMP, filtrable por Sede."""
    filter_sede = request.args.get('sede', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    sql_where_all = " WHERE 1=1"
    params_all = []
    if filter_sede:
        sql_where_all += " AND UPPER(sede) = UPPER(?)"
        params_all.append(filter_sede)

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where_all}", params_all)
    total_inventario = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where_all} AND UPPER(cumplimiento_pmp) = 'NO APLICA'", params_all)
    total_no_aplica = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where_all} AND UPPER(cumplimiento_pmp) = 'BAJA'", params_all)
    total_baja = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where_all} AND UPPER(cumplimiento_pmp) = 'REALIZADO'", params_all)
    total_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where_all} AND UPPER(cumplimiento_pmp) = 'NO REALIZADO'", params_all)
    total_no_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos {sql_where_all} AND UPPER(cumplimiento_pmp) = 'A FUTURO'", params_all)
    total_a_futuro = cursor.fetchone()[0]

    # Justificaciones de NO APLICA
    sql_razones_na = f'''
        SELECT COALESCE(NULLIF(TRIM(observacion), ''), 'Garantía extendida / Apoyo tecnológico / Sin contrato N2') as razon, COUNT(*)
        FROM equipos
        {sql_where_all} AND UPPER(cumplimiento_pmp) = 'NO APLICA'
        GROUP BY razon
        ORDER BY COUNT(*) DESC
        LIMIT 10
    '''
    cursor.execute(sql_razones_na, params_all)
    razones_no_aplica = [{"razon": r[0], "cantidad": r[1]} for r in cursor.fetchall()]

    conn.close()

    total_pmp = total_realizado + total_no_realizado + total_a_futuro

    return jsonify({
        "sede": filter_sede if filter_sede else "Todas las Sedes",
        "total_inventario": total_inventario,
        "total_pmp": total_pmp,
        "total_no_aplica": total_no_aplica,
        "total_baja": total_baja,
        "total_realizado": total_realizado,
        "total_no_realizado": total_no_realizado,
        "total_a_futuro": total_a_futuro,
        "porcentaje_cumplimiento": round((total_realizado / total_pmp * 100), 1) if total_pmp > 0 else 0,
        "razones_no_aplica": razones_no_aplica
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
               frecuencia_pmp, meses_programados, ultimo_mantenimiento, aplazado, cumplimiento_pmp, observacion
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
                "cumplimiento_pmp": equipo[12] if equipo[12] else "NO APLICA",
                "observacion": equipo[13] if equipo[13] else ""
            }
        })
    return jsonify({"existe": False})

@app.route('/cargar-excel', methods=['POST'])
def cargar_excel():
    if 'archivo_excel' not in request.files:
        return jsonify({"status": "error", "message": "No se adjuntó ningún archivo"}), 400
    
    file = request.files['archivo_excel']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nombre de archivo inválido"}), 400

    try:
        file_bytes = io.BytesIO(file.read())
        df_raw = pd.read_excel(file_bytes, sheet_name=0, header=None)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        agregados = 0
        omitidos = 0

        col_obs_final = 84 if df_raw.shape[1] > 84 else (79 if df_raw.shape[1] > 79 else -1)

        for r_idx in range(4, len(df_raw)):
            nombre = str(df_raw.iloc[r_idx, 0]).strip() if pd.notna(df_raw.iloc[r_idx, 0]) else ""
            serial = str(df_raw.iloc[r_idx, 3]).strip() if pd.notna(df_raw.iloc[r_idx, 3]) else ""

            if not nombre or not serial or serial.upper() in ['NAN', 'NONE', 'NO APLICA', 'SIN SERIE', '']:
                serial = f"INV-{r_idx}-{str(df_raw.iloc[r_idx, 4]).strip()}"

            marca = str(df_raw.iloc[r_idx, 1]).strip() if pd.notna(df_raw.iloc[r_idx, 1]) else ""
            modelo = str(df_raw.iloc[r_idx, 2]).strip() if pd.notna(df_raw.iloc[r_idx, 2]) else ""
            num_inv = str(df_raw.iloc[r_idx, 4]).strip() if pd.notna(df_raw.iloc[r_idx, 4]) else ""
            sede = str(df_raw.iloc[r_idx, 21]).strip() if pd.notna(df_raw.iloc[r_idx, 21]) else "Sin Sede"
            ubicacion = str(df_raw.iloc[r_idx, 22]).strip() if pd.notna(df_raw.iloc[r_idx, 22]) else ""
            frecuencia = str(df_raw.iloc[r_idx, 77]).strip() if pd.notna(df_raw.iloc[r_idx, 77]) else ""
            meses_prog = str(df_raw.iloc[r_idx, 78]).strip() if pd.notna(df_raw.iloc[r_idx, 78]) else ""
            
            observacion = ""
            if col_obs_final != -1 and pd.notna(df_raw.iloc[r_idx, col_obs_final]):
                observacion = str(df_raw.iloc[r_idx, col_obs_final]).strip()
            elif df_raw.shape[1] > 79 and pd.notna(df_raw.iloc[r_idx, 79]):
                observacion = str(df_raw.iloc[r_idx, 79]).strip()

            estado_final_raw = str(df_raw.iloc[r_idx, 82]).strip().upper() if df_raw.shape[1] > 82 and pd.notna(df_raw.iloc[r_idx, 82]) else "NO APLICA"

            if estado_final_raw in ['REALIZADO', 'NO REALIZADO', 'A FUTURO', 'NO APLICA', 'BAJA']:
                cumplimiento = estado_final_raw
            else:
                cumplimiento = "NO APLICA"

            try:
                cursor.execute('''
                    INSERT INTO equipos (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion, estado, 
                                        frecuencia_pmp, meses_programados, ultimo_mantenimiento, aplazado, cumplimiento_pmp, observacion)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Operativo', ?, ?, '', 'No', ?, ?)
                ''', (nombre, marca, modelo, serial, num_inv, sede, ubicacion, frecuencia, meses_prog, cumplimiento, observacion))
                agregados += 1
            except sqlite3.IntegrityError:
                omitidos += 1

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": f"Base de datos actualizada correctamente. Registros procesados: {agregados}. Duplicados: {omitidos}."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error procesando archivo: {str(e)}"}), 500

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
                    frecuencia_pmp, meses_programados, ultimo_mantenimiento, aplazado, cumplimiento_pmp, observacion 
             FROM equipos WHERE 1=1'''
    params = []

    if filter_sede:
        sql += ' AND UPPER(sede) = UPPER(?)'
        params.append(filter_sede)

    if filter_cumplimiento:
        sql += ' AND UPPER(cumplimiento_pmp) = UPPER(?)'
        params.append(filter_cumplimiento.upper())

    if query:
        search_pattern = f"%{query}%"
        sql += ' AND (nombre LIKE ? OR serial LIKE ? OR numero_inventario LIKE ? OR marca LIKE ? OR ubicacion LIKE ?)'
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

    sql += ' ORDER BY id DESC LIMIT 300'

    cursor.execute(sql, params)
    filas = cursor.fetchall()
    conn.close()

    equipos = [{
        "id": f[0], "nombre": f[1], "marca": f[2], "modelo": f[3], "serial": f[4], 
        "numero_inventario": f[5], "sede": f[6], "ubicacion": f[7], "estado": f[8],
        "frecuencia_pmp": f[9], "meses_programados": f[10], "ultimo_mantenimiento": f[11],
        "aplazado": f[12], "cumplimiento_pmp": f[13], "observacion": f[14]
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
               sede AS SEDE, ubicacion AS UBICACION,
               frecuencia_pmp AS "FRECUENCIA PMP", meses_programados AS "MESES PROGRAMADOS",
               cumplimiento_pmp AS "ESTADO FINAL PMP", observacion AS "OBSERVACIONES FINAL (CAUSAL)"
        FROM equipos WHERE 1=1
    '''
    params = []

    if filter_sede:
        sql += ' AND UPPER(sede) = UPPER(?)'
        params.append(filter_sede)

    if filter_cumplimiento:
        sql += ' AND UPPER(cumplimiento_pmp) = UPPER(?)'
        params.append(filter_cumplimiento.upper())

    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario_PMP')
    
    output.seek(0)
    filename = f"Inventario_PMP_{filter_sede if filter_sede else 'General'}.xlsx".replace(' ', '_')
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
