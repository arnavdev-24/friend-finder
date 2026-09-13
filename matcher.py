import mysql.connector
import os
def get_connection():
    return mysql.connector.connect(

        host="mysql-1d4d74e5-friend-finder.g.aivencloud.com",
        user="avnadmin",
        password="AVNS_V1OcVdOvBjm-6ehvMwk",
        database="defaultdb",
        port="23608"
)




def get_user_responses(user_id):
    conn=get_connection()
    cursor=conn.cursor()
    cursor.execute(
        "SELECT question_id, value_number FROM responses WHERE user_id=%s",
        (user_id,)
    )
    data={q: v for q, v in cursor.fetchall()}
    cursor.close()
    conn.close()
    return data
'''
short hand for the above function:
result = {}
for q,v in cursor.fetchall():
    result[q] = v
return result
'''
def similarity(a,b):
    return 1-abs(a-b)/4

def get_prefernces(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT question_id, importance, openness "
            "FROM preferences_meta WHERE user_id=%s",
            (user_id,),
        )
        data = {q: (importance, openness) for q, importance, openness in cursor.fetchall()}
    except mysql.connector.Error as error:
        if error.errno != 1146:
            raise
        data = {}
    finally:
        cursor.close()
        conn.close()

    return data



def calculate_match_with_explanation(u1,u2):
    r1=get_user_responses(u1)
    r2=get_user_responses(u2)
    p1=get_prefernces(u1)


    total=0
    weight_sum=0

    explanations=[]

    for q in r1:
        if q in r2:
            a=r1[q]
            b=r2[q]
            base_sim=similarity(a,b)
            if q in p1:
                importance, openness = p1[q]
            else:
                importance, openness = 3, 3
            adjusted_sim=base_sim + (openness/5) *(1-base_sim)
            total+=adjusted_sim*importance
            weight_sum+=importance

            if importance >= 4:
                if base_sim > 0.7:
                    explanations.append({
                        "question_id":q,
                        "label":"very similar",
                        "important": True
                    })
                elif base_sim < 0.3:
                    explanations.append({
                        "question_id":q,
                        "label":"very different",
                        "important": True
                    })
            else:
                if base_sim > 0.7:
                    explanations.append({
                        "question_id":q,
                        "label":"similar",
                        "important": False
                    })
                elif base_sim < 0.3:
                    explanations.append({
                        "question_id":q,
                        "label":"different",
                        "important": False
                    })

    if weight_sum == 0:
        return 0, []

    score = round((total / weight_sum) * 100, 2)

    return score, explanations

    
    # if count==0:
    #     return 0
    # return round((total/count)*100,2)

def get_top_matches(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM users WHERE id != %s", (user_id,))
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    results = []

    for uid, name in users:
        score, reasons = calculate_match_with_explanation(user_id, uid)
        results.append((uid, name, score, reasons))

    results.sort(key=lambda x: x[2], reverse=True)

    return results[:5]

# def get_top_matches(user_id):
#     conn=get_connection()
#     cursor=conn.cursor()
#     cursor.execute("select id, name from users where id != %s", (user_id,))
#     users = cursor.fetchall()

#     cursor.close()
#     conn.close()

#     results = []
#     for uid,name in users:
#         score = calculate_match(user_id, uid)
#         results.append((name,score))

#     results.sort(key=lambda x: x[1], reverse=True)

#     return results[:5]  # Return top 5 matches

if __name__ == "__main__":
    matches = get_top_matches(1)
    for uid, name, score, reasons in matches:
        print(f"\n{name} → {score}%")
        for r in reasons:
            print(" -", r)
