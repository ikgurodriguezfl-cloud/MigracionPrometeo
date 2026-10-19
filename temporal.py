import pymysql

try:
    conn = pymysql.connect(
        host='localhost',
        port=3306,
        user='root',
        password='alpha1234',
        database='prometeo_marc',
        charset='utf8mb4'
    )
    print("¡Conexión exitosa!")
    conn.close()
except Exception as e:
    print("Error de conexión:", e)
espera = input()