import threading

import mysql.connector
from mysql.connector import pooling


_pool = None
_pool_lock = threading.Lock()

DB_CONFIG = {
    "host": "mysql-1d4d74e5-friend-finder.g.aivencloud.com",
    "user": "avnadmin",
    "password": "AVNS_V1OcVdOvBjm-6ehvMwk",
    "database": "defaultdb",
    "port": 23608,
    "connection_timeout": 5,
}


MATCH_WEIGHTS = {
    1: 5,
    2: 4,
    3: 3,
    4: 3,
    5: 2,
    6: 1,
    7: 2,
    8: 2,
}


def get_connection():
    global _pool

    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pooling.MySQLConnectionPool(
                    pool_name="friend_finder_pool",
                    pool_size=5,
                    pool_reset_session=True,
                    **DB_CONFIG,
                )

    return _pool.get_connection()




def get_user_responses(user_id):
    conn=get_connection()
    cursor=conn.cursor()
    cursor.execute(
        """
        SELECT question_id, value_number
        FROM responses
        WHERE user_id=%s AND question_id BETWEEN 1 AND 8
        """,
        (user_id,)
    )
    data={q: v for q, v in cursor.fetchall()}
    cursor.close()
    conn.close()
    return data

def similarity(a,b):
    return max(0, 1 - (abs(a - b) / 9))


def passes_filters(current_user, candidate_user):
    current_preferred_gender = current_user.get("preferred_gender")
    candidate_gender = candidate_user.get("gender")
    if (
        current_preferred_gender in {"male", "female"}
        and candidate_gender
        and current_preferred_gender != candidate_gender
    ):
        return False

    candidate_preferred_gender = candidate_user.get("preferred_gender")
    current_gender = current_user.get("gender")
    if (
        candidate_preferred_gender in {"male", "female"}
        and current_gender
        and candidate_preferred_gender != current_gender
    ):
        return False

    if (
        current_user.get("preferred_year") == "same"
        and current_user.get("year") is not None
        and candidate_user.get("year") is not None
        and current_user["year"] != candidate_user["year"]
    ):
        return False

    if (
        candidate_user.get("preferred_year") == "same"
        and current_user.get("year") is not None
        and candidate_user.get("year") is not None
        and current_user["year"] != candidate_user["year"]
    ):
        return False

    return True

def get_prefernces(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT question_id, importance, openness
            FROM preferences_meta
            WHERE user_id=%s AND question_id BETWEEN 9 AND 12
            """,
            (user_id,),
        )
        return {
            question_id: (importance, openness)
            for question_id, importance, openness in cursor.fetchall()
        }
    except mysql.connector.Error as error:
        if error.errno != 1146:
            raise
        return {}
    finally:
        cursor.close()
        conn.close()



def calculate_match_with_explanation(u1, u2, responses=None, preferences=None):
    if responses is None:
        responses = {u1: get_user_responses(u1), u2: get_user_responses(u2)}
    if preferences is None:
        preferences = {u1: get_prefernces(u1)}

    r1 = responses.get(u1, {})
    r2 = responses.get(u2, {})
    p1 = preferences.get(u1, {})


    total = 0
    total_weight = 0

    explanations=[]

    for q, weight in MATCH_WEIGHTS.items():
        if q in r1 and q in r2:
            a=r1[q]
            b=r2[q]
            base_sim=similarity(a,b)
            total += base_sim * weight
            total_weight += weight

            difference = abs(a - b)
            if difference <= 1:
                label = "very similar"
            elif difference <= 3:
                label = "somewhat similar"
            else:
                label = "different"
            explanations.append({
                "question_id": q,
                "label": label,
                "important": weight >= 4,
            })

    if total_weight == 0:
        return 0, []

    score = round((total / total_weight) * 100, 2)

    return score, explanations

    
    # if count==0:
    #     return 0
    # return round((total/count)*100,2)

def get_top_matches(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, name, gender, preferred_gender, `year`, preferred_year
        FROM users
        """
    )
    user_rows = cursor.fetchall()

    cursor.execute(
        """
        SELECT user_id, question_id, value_number
        FROM responses
        WHERE question_id BETWEEN 1 AND 8
        """
    )
    response_data = {}
    for uid, question_id, value in cursor.fetchall():
        response_data.setdefault(uid, {})[question_id] = value

    preference_data = {}
    try:
        cursor.execute(
            """
            SELECT user_id, question_id, importance, openness
            FROM preferences_meta
            WHERE question_id BETWEEN 9 AND 12
            """
        )
        for uid, question_id, importance, openness in cursor.fetchall():
            preference_data.setdefault(uid, {})[question_id] = (importance, openness)
    except mysql.connector.Error as error:
        if error.errno != 1146:
            raise

    cursor.close()
    conn.close()

    user_data = {
        user_id: {
            "id": user_id,
            "gender": None,
            "preferred_gender": None,
            "year": None,
            "preferred_year": None,
        }
    }
    users = []
    for uid, name, gender, preferred_gender, year, preferred_year in user_rows:
        user_data[uid] = {
            "id": uid,
            "gender": gender,
            "preferred_gender": preferred_gender,
            "year": year,
            "preferred_year": preferred_year,
        }
        if uid != user_id:
            users.append((uid, name))

    results = []

    for uid, name in users:
        if not passes_filters(user_data[user_id], user_data[uid]):
            continue
        score, reasons = calculate_match_with_explanation(
            user_id,
            uid,
            responses=response_data,
            preferences=preference_data,
        )
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
