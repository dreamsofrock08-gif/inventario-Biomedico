from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import pandas as pd
import io

app = Flask(__name__)
CORS(app)
DB_NAME = "dashboard_pmp.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS equipos_pmp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            marca TEXT,
            modelo TEXT,
            serial TEXT UNIQUE NOT NULL,
            numero_inventario TEXT,
            sede TEXT,
            ubicacion TEXT,
            frecuencia_pmp TEXT,
            meses_programados TEXT,
            cumplimiento_pmp TEXT,
            observacion TEXT,
            envio_correo TEXT,
            equipo_no_ubicado TEXT,
            programado_resto_ano TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

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

        # Limpiar base previa para reflejar exactamente la nueva carga
        cursor.execute("DELETE FROM equipos_pmp")

        agregados = 0

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
            
            frecuencia = ""
            if df_raw.shape[1] > 77 and pd.notna(df_raw.iloc[r_idx, 77]):
                frecuencia = str(df_raw.iloc[r_idx, 77]).strip()

            meses_prog = ""
            if df_raw.shape[1] > 78 and pd.notna(df_raw.iloc[r_idx, 78]):
                meses_prog = str(df_raw.iloc[r_idx, 78]).strip()

            # Búsqueda dinámica del estado final (REALIZADO, NO REALIZADO, A FUTURO, NO APLICA, BAJA)
            cumplimiento = "NO APLICA"
            for col_search in range(df_raw.shape[1] - 1, 70, -1):
                val_cell = str(df_raw.iloc[r_idx, col_search]).strip().upper() if pd.notna(df_raw.iloc[r_idx, col_search]) else ""
                if val_cell in ['REALIZADO', 'NO REALIZADO', 'A FUTURO', 'NO APLICA', 'BAJA']:
                    cumplimiento = val_cell
                    break

            # Observación final (Revisar últimas columnas)
            observacion = ""
            for col_obs in [84, 83, 79]:
                if df_raw.shape[1] > col_obs and pd.notna(df_raw.iloc[r_idx, col_obs]):
                    val_obs = str(df_raw.iloc[r_idx, col_obs]).strip()
                    if val_obs.upper() not in ['REALIZADO', 'NO REALIZADO', 'A FUTURO', 'NO APLICA', 'BAJA', 'NAN', 'NONE']:
                        observacion = val_obs
                        break

            # Banderas personalizadas
            no_ubicado = "SI" if "NO UBICADO" in observacion.upper() else "NO"
            a_futuro = "SI" if cumplimiento == "A FUTURO" else "NO"
            checking_correo = "PENDIENTE" if cumplimiento == "NO REALIZADO" else "NO REQUIERE"

            try:
                cursor.execute('''
                    INSERT INTO equipos_pmp (nombre, marca, modelo, serial, numero_inventario, sede, ubicacion,
                                            frecuencia_pmp, meses_programados, cumplimiento_pmp, observacion,
                                            envio_correo, equipo_no_ubicado, programado_resto_ano)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (nombre, marca, modelo, serial, num_inv, sede, ubicacion, frecuencia, meses_prog, 
                      cumplimiento, observacion, checking_correo, no_ubicado, a_futuro))
                agregados += 1
            except sqlite3.IntegrityError:
                pass

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": f"Base de datos del Dashboard procesada con éxito. Registros importados: {agregados}."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error procesando archivo: {str(e)}"}), 500

@app.route('/datos-dashboard', methods=['GET'])
def datos_dashboard():
    filter_sede = request.args.get('sede', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    sql_where = " WHERE UPPER(cumplimiento_pmp) NOT IN ('NO APLICA', 'BAJA')"
    params = []

    if filter_sede:
        sql_where += " AND UPPER(sede) = UPPER(?)"
        params.append(filter_sede)

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where}", params)
    total_equipos_pmp = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where} AND UPPER(cumplimiento_pmp) = 'REALIZADO'", params)
    total_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where} AND UPPER(cumplimiento_pmp) = 'NO REALIZADO'", params)
    total_no_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where} AND UPPER(cumplimiento_pmp) = 'A FUTURO'", params)
    total_a_futuro = cursor.fetchone()[0]

    cursor.execute(f'''
        SELECT COALESCE(NULLIF(TRIM(observacion), ''), 'Sin observación registrada') as razon, COUNT(*) 
        FROM equipos_pmp 
        {sql_where} AND UPPER(cumplimiento_pmp) = 'NO REALIZADO'
        GROUP BY razon
        ORDER BY COUNT(*) DESC
    ''', params)
    razones_no_realizado = [{"razon": row[0], "cantidad": row[1]} for row in cursor.fetchall()]

    cursor.execute('''
        SELECT sede, 
               SUM(CASE WHEN UPPER(cumplimiento_pmp) = 'REALIZADO' THEN 1 ELSE 0 END) as realizado,
               SUM(CASE WHEN UPPER(cumplimiento_pmp) = 'NO REALIZADO' THEN 1 ELSE 0 END) as no_realizado,
               SUM(CASE WHEN UPPER(cumplimiento_pmp) = 'A FUTURO' THEN 1 ELSE 0 END) as a_futuro
        FROM equipos_pmp 
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
        "porcentaje_cumplimiento": porcentaje_cumplimiento,
        "razones_no_realizado": razones_no_realizado,
        "sedes_stats": [{
            "sede": s[0], "realizado": s[1], "no_realizado": s[2], "a_futuro": s[3]
        } for s in sedes_data]
    })

@app.route('/generar-informe-ejecutivo', methods=['GET'])
def generar_informe_ejecutivo():
    filter_sede = request.args.get('sede', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    sql_where_all = " WHERE 1=1"
    params_all = []
    if filter_sede:
        sql_where_all += " AND UPPER(sede) = UPPER(?)"
        params_all.append(filter_sede)

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where_all}", params_all)
    total_inventario = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where_all} AND UPPER(cumplimiento_pmp) = 'NO APLICA'", params_all)
    total_no_aplica = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where_all} AND UPPER(cumplimiento_pmp) = 'BAJA'", params_all)
    total_baja = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where_all} AND UPPER(cumplimiento_pmp) = 'REALIZADO'", params_all)
    total_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where_all} AND UPPER(cumplimiento_pmp) = 'NO REALIZADO'", params_all)
    total_no_realizado = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM equipos_pmp {sql_where_all} AND UPPER(cumplimiento_pmp) = 'A FUTURO'", params_all)
    total_a_futuro = cursor.fetchone()[0]

    cursor.execute(f'''
        SELECT COALESCE(NULLIF(TRIM(observacion), ''), 'Garantía extendida / Apoyo tecnológico / Sin contrato N2') as razon, COUNT(*)
        FROM equipos_pmp
        {sql_where_all} AND UPPER(cumplimiento_pmp) = 'NO APLICA'
        GROUP BY razon
        ORDER BY COUNT(*) DESC
        LIMIT 10
    ''', params_all)
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
    cursor.execute("SELECT DISTINCT sede FROM equipos_pmp WHERE sede IS NOT NULL AND TRIM(sede) != '' ORDER BY sede ASC")
    sedes = [f[0] for f in cursor.fetchall()]
    conn.close()
    return jsonify(sedes)

@app.route('/descargar-excel-dashboard', methods=['GET'])
def descargar_excel_dashboard():
    filter_sede = request.args.get('sede', '').strip()
    
    conn = sqlite3.connect(DB_NAME)
    sql = '''
        SELECT 
            serial AS "SERIAL",
            numero_inventario AS "NUMERO DE INVENTARIO",
            nombre AS "NOMBRE DEL EQUIPO",
            sede AS "SEDE",
            frecuencia_pmp AS "FRECUENCIA",
            cumplimiento_pmp AS "ESTADO",
            observacion AS "CAUSA / OBSERVACION",
            envio_correo AS "ENVIO CORREO / CHECKING",
            equipo_no_ubicado AS "EQUIPO NO UBICADO",
            programado_resto_ano AS "PROGRAMADO RESTO DEL AÑO"
        FROM equipos_pmp 
        WHERE 1=1
    '''
    params = []

    if filter_sede:
        sql += ' AND UPPER(sede) = UPPER(?)'
        params.append(filter_sede)

    sql += ' ORDER BY sede ASC, cumplimiento_pmp ASC'

    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Dashboard_PMP_Reporte')
    
    output.seek(0)
    filename = f"Reporte_Dashboard_PMP_{filter_sede if filter_sede else 'General'}.xlsx".replace(' ', '_')
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
