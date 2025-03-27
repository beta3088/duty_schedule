class Config:
    SECRET_KEY = 'your-secret-key'  # 更换为安全的密钥
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:your_password@localhost/duty_schedule'
    SQLALCHEMY_TRACK_MODIFICATIONS = False