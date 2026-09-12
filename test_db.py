import mysql.connector
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root123",
    database="friend_finder"
)
cursor = conn.cursor()

query="insert into users (name,email,roll_no) values (%s,%s,%s)"
# values=('Arnav Saxena', 'asaxena3_be26@thapar.edu', '1026060247')
# cursor.execute(query,values)
# conn.commit()
values=('s1', '1@thapar.edu', '101')
cursor.execute(query,values)
conn.commit()
values=('s2', '2@thapar.edu', '102')
cursor.execute(query,values)
conn.commit()
values=('s3', '3@thapar.edu', '103')
cursor.execute(query,values)
conn.commit()

# # 🔹 Insert responses for user 1
# cursor.execute(
#     "INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, %s, %s)",
#     (4, 1, 5)
# )

# cursor.execute(
#     "INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, %s, %s)",
#     (4, 2, 3)
# )

# # 🔹 Insert responses for user 2
# cursor.execute(
#     "INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, %s, %s)",
#     (5, 1, 4)
# )

# cursor.execute(
#     "INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, %s, %s)",
#     (5, 2, 3)
# )

# conn.commit()

# print("User added successfully!")



cursor.execute("SELECT * FROM users")

for row in cursor.fetchall():
    print(row)

conn.close()