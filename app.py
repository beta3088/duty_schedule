from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import date, datetime, timedelta
import logging
import random
import calendar

app = Flask(__name__)
app.config.from_object('config.Config')

# 启用 Jinja2 的 'do' 扩展
app.jinja_env.add_extension('jinja2.ext.do')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 日志配置
logging.basicConfig(filename='schedule_web.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# 用户模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)  # 测试环境明文
    is_admin = db.Column(db.Boolean, default=False)

# 人员模型
class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

# 排班模型
class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    staff = db.relationship('Staff', backref='schedules')

# 节假日模型
class Holiday(db.Model):
    date = db.Column(db.Date, primary_key=True)
    is_workday = db.Column(db.Boolean, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))  # 修改为 db.session.get()

# 全局员工颜色映射
staff_colors = {}

# 初始化员工颜色
def init_staff_colors():
    global staff_colors
    if not staff_colors:
        for staff in Staff.query.all():
            staff_colors[staff.name] = f'#{random.randint(0, 16777215):06x}'
    logging.info(f"Initialized staff colors: {staff_colors}")

# 登录页面（仅管理员）
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username, password=password).first()
        if user and user.is_admin:
            login_user(user)
            logging.info(f"管理员 {username} 登录成功")
            return redirect(url_for('index'))
        else:
            flash('登录失败，仅限管理员账户')
            logging.warning(f"用户 {username} 登录失败")
            return render_template('login.html'), 401
    return render_template('login.html')

# 退出登录
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# 主页 - 日历视图（无需登录）
@app.route('/', methods=['GET'])
def index():
    year = int(request.args.get('year', date.today().year))
    schedules = Schedule.query.filter(Schedule.date.between(f'{year}-01-01', f'{year}-12-31')).all()
    # 初始化员工颜色
    init_staff_colors()
    monthly_schedules = {}
    monthly_calendars = {}
    for month in range(1, 13):
        monthly_schedules[month] = {
            sched.date.day: {
                'name': sched.staff.name,
                'color': staff_colors[sched.staff.name]  # 使用固定的员工颜色
            } for sched in schedules if sched.date.month == month
        }
        monthly_calendars[month] = calendar.monthcalendar(year, month)
    logging.info(f"Year: {year}, Schedules count: {len(schedules)}")
    is_admin_user = current_user.is_authenticated and current_user.is_admin
    return render_template('index.html', monthly_schedules=monthly_schedules, 
                         monthly_calendars=monthly_calendars, year=year, 
                         is_admin=is_admin_user)

# 初始化排班（仅管理员）
@app.route('/init_schedule', methods=['POST'])
@login_required
def init_schedule():
    if not current_user.is_admin:
        flash('无权限访问')
        return redirect(url_for('index')), 403
    year = int(request.form['year'])
    Schedule.query.filter(Schedule.date.between(f'{year}-01-01', f'{year}-12-31')).delete()
    staff = Staff.query.all()
    if not staff:
        flash('请先添加人员')
        return redirect(url_for('index'))
    holidays = {h.date: h.is_workday for h in Holiday.query.all()}
    current_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    staff_idx = 0
    while current_date <= end_date:
        if (current_date.weekday() < 5 and (current_date not in holidays or holidays[current_date])) or \
           (current_date in holidays and holidays[current_date]):
            staff_member = staff[staff_idx % len(staff)]
            if staff_member.name == '莫' and current_date.weekday() == 0:
                prev_date = current_date - timedelta(days=1)
                prev_schedule = Schedule.query.filter_by(date=prev_date).first()
                if prev_schedule:
                    prev_schedule.staff = staff_member
                    db.session.add(Schedule(date=current_date, staff=prev_schedule.staff))
            else:
                db.session.add(Schedule(date=current_date, staff=staff_member))
            staff_idx += 1
        current_date += timedelta(days=1)
    db.session.commit()
    logging.info(f"{year} 年排班初始化成功")
    flash(f'{year} 年排班初始化完成')
    return redirect(url_for('index', year=year))

# 更新排班（仅管理员）
@app.route('/update', methods=['GET', 'POST'])
@login_required
def update_schedule():
    if not current_user.is_admin:
        flash('无权限访问')
        return redirect(url_for('index')), 403
    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        if start_date < date.today():
            flash('开始日期不能早于当前日期')
            return redirect(url_for('update_schedule'))
        delete_staff = request.form.get('delete_staff')
        if delete_staff:
            staff = Staff.query.filter_by(name=delete_staff).first()
            if staff:
                Schedule.query.filter(Schedule.staff_id == staff.id, Schedule.date >= start_date).delete()
                db.session.delete(staff)
                staff_colors.pop(staff.name, None)  # 删除员工时移除颜色
        new_staff = request.form.get('new_staff')
        if new_staff:
            new_staff_obj = Staff(name=new_staff)
            db.session.add(new_staff_obj)
            staff_colors[new_staff] = f'#{random.randint(0, 16777215):06x}'  # 为新员工分配颜色
        db.session.commit()
        logging.info('排班更新成功')
        flash(f'排班更新完成，从 {start_date} 开始')
        return redirect(url_for('index'))
    return render_template('update.html', staff=Staff.query.all())

# 拖拽对调（仅管理员）
@app.route('/swap', methods=['POST'])
@login_required
def swap():
    if not current_user.is_admin:
        return '无权限', 403
    date1 = datetime.strptime(request.form['date1'], '%Y-%m-%d').date()
    date2 = datetime.strptime(request.form['date2'], '%Y-%m-%d').date()
    sched1 = Schedule.query.filter_by(date=date1).first()
    sched2 = Schedule.query.filter_by(date=date2).first()
    if sched1 and sched2:
        sched1.staff, sched2.staff = sched2.staff, sched1.staff
        db.session.commit()
        logging.info('人员对调成功')
        return '成功', 200
    return '日期无排班数据', 400

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.first():
            db.session.add_all([
                User(username='admin', password='admin123', is_admin=True),
                User(username='user', password='user123', is_admin=False),
                Staff(name='刘'), Staff(name='谭'), Staff(name='莫'), Staff(name='张'), Staff(name='王')
            ])
            db.session.commit()
    app.run(debug=True)