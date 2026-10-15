"""Qt interface for ORBITclip SQL Explorer. Loads no table rows, only metadata."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal, QObject, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QPainterPath, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QSpinBox, QCheckBox, QStackedWidget, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGraphicsScene, QGraphicsView,
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsPathItem, QFrame
)

from orbit_sql_core import (
    profile_key, table_id, split_table_id, new_project, load_project,
    save_project, field_note_key, manual_join, visible_links, discover_tables,
    inspect_tables, SSL_MODES
)


class TaskSignals(QObject):
    done = Signal(str, object)
    failed = Signal(str, str)


class GraphCard(QGraphicsRectItem):
    def __init__(self, identity, metadata, position_callback, line_callback):
        columns = metadata['columns']
        shown = columns[:24]
        height = 45 + 18 * len(shown) + (20 if len(columns) > len(shown) else 0)
        super().__init__(0, 0, 260, height)
        self.identity = identity
        self.position_callback = position_callback
        self.line_callback = line_callback
        self.setBrush(QBrush(QColor('#20313E')))
        self.setPen(QPen(QColor('#617E91'), 1.2))
        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
        schema, name = split_table_id(identity)
        title = QGraphicsTextItem(f'{schema}.{name}', self)
        title.setDefaultTextColor(QColor('#FFBB9E'))
        font = QFont(); font.setPointSize(10); font.setBold(True)
        title.setFont(font)
        title.setPos(7, 4)
        y = 32
        for c in shown:
            mark = '◆ ' if c['pk'] else ('⇢ ' if c['fk'] else '   ')
            text = QGraphicsTextItem(mark + c['name'][:24] + '  ·  ' + c['type'][:16], self)
            text.setDefaultTextColor(QColor('#E0EDF3') if c['pk'] else QColor('#ABBEC9'))
            text.setPos(6, y)
            small = text.font(); small.setPointSize(8); text.setFont(small)
            y += 18
        if len(columns) > len(shown):
            more = QGraphicsTextItem(f'+ {len(columns)-len(shown)} полей (см. вкладку Поля)', self)
            more.setDefaultTextColor(QColor('#93A5B1')); more.setPos(8, y)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            if self.line_callback:
                self.line_callback()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.position_callback(self.identity, self.pos())


class SQLExplorer(QWidget):
    """Independent non-modal SQL workspace, isolated from clipboard and messenger."""
    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowTitle('ORBITclip · SQL Explorer')
        self.resize(1180, 790)
        self.setMinimumSize(790, 550)
        self.profile = None
        self.project = new_project()
        self.config = None                 # password lives in memory only
        self.available = []
        self.details = {}
        self.cards = {}
        self.paths = []
        self.generation = 0
        self.signals = TaskSignals(self)
        self.signals.done.connect(self.on_task_done)
        self.signals.failed.connect(self.on_task_failed)
        self.build()

    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        heading = QHBoxLayout()
        caption = QLabel('SQL Explorer')
        caption.setStyleSheet('font-size:20px;font-weight:700;color:#F7B69E;')
        heading.addWidget(caption)
        self.status = QLabel('Не подключено · пароль не сохраняется')
        heading.addWidget(self.status)
        heading.addStretch()
        heading.addWidget(QLabel('v7.3.0'))
        outer.addLayout(heading)
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(175)
        for name in ('Подключение', 'Таблицы', 'Поля', 'Связи', 'ER-схема'):
            self.navigation.addItem(name)
        self.navigation.currentRowChanged.connect(self.change_page)
        body.addWidget(self.navigation)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.build_connection()
        self.build_tables()
        self.build_columns()
        self.build_joins()
        self.build_diagram()
        self.navigation.setCurrentRow(0)

    def build_connection(self):
        page = QWidget(); l = QVBoxLayout(page)
        l.addWidget(QLabel('Подключение к PostgreSQL'))
        self.host = QLineEdit(); self.host.setPlaceholderText('server.example.org')
        self.host.setText('localhost')
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(5432)
        self.database = QLineEdit(); self.database.setPlaceholderText('Имя базы')
        self.user = QLineEdit(); self.user.setPlaceholderText('Пользователь с правами на чтение')
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.ssl = QComboBox()
        for mode in SSL_MODES: self.ssl.addItem(mode)
        self.ssl.setCurrentText('verify-full')
        for text, widget in [('Хост',self.host),('Порт',self.port),('База данных',self.database),
                              ('Пользователь',self.user),('Пароль (только на эту сессию)',self.password),
                              ('Проверка TLS',self.ssl)]:
            l.addWidget(QLabel(text)); l.addWidget(widget)
        l.addWidget(QLabel('По умолчанию используется verify-full: проверяется сертификат и имя сервера.\n'
                           'Если подключаешься к локальной БД без TLS, выбери другой режим осознанно.'))
        connect = QPushButton('Подключиться и загрузить список таблиц')
        connect.clicked.connect(self.start_connect)
        l.addWidget(connect);l.addStretch();self.pages.addWidget(page)

    def build_tables(self):
        page = QWidget();lay=QVBoxLayout(page)
        lay.addWidget(QLabel('Отметь нужные таблицы, затем нажми «Загрузить поля».'))
        self.filter = QLineEdit();self.filter.setPlaceholderText('Фильтр схем и таблиц…')
        self.filter.textChanged.connect(self.filter_tables)
        lay.addWidget(self.filter)
        buttons=QHBoxLayout()
        for name, fn in [('Выбрать видимые',lambda:self.mark_visible(True)),
                         ('Снять с видимых',lambda:self.mark_visible(False)),
                         ('Загрузить поля',self.start_inspect)]:
            b=QPushButton(name);b.clicked.connect(fn);buttons.addWidget(b)
        lay.addLayout(buttons)
        self.table_tree=QTreeWidget();self.table_tree.setHeaderLabels(['Схема / таблица','Описание в БД'])
        self.table_tree.setRootIsDecorated(True)
        self.table_tree.itemChanged.connect(self.table_checked)
        lay.addWidget(self.table_tree,1)
        self.table_count=QLabel('Нет списка таблиц')
        lay.addWidget(self.table_count);self.pages.addWidget(page)

    def build_columns(self):
        page=QWidget();l=QHBoxLayout(page)
        self.column_tables=QListWidget();self.column_tables.setMinimumWidth(205)
        self.column_tables.currentItemChanged.connect(self.refresh_columns)
        l.addWidget(self.column_tables, 1)
        self.columns=QTableWidget(0,5)
        self.columns.setHorizontalHeaderLabels(['Поле','Тип','Ключ','Комментарий БД','Мой комментарий'])
        self.columns.horizontalHeader().setSectionResizeMode(4,QHeaderView.Stretch)
        self.columns.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents)
        self.columns.itemChanged.connect(self.save_field_note)
        l.addWidget(self.columns,4);self.pages.addWidget(page)

    def build_joins(self):
        page=QWidget();l=QVBoxLayout(page)
        l.addWidget(QLabel('Создай дополнительное соединение по полям. Внешние ключи БД определяются автоматически.'))
        self.left_table=QComboBox();self.right_table=QComboBox()
        self.left_field=QComboBox();self.right_field=QComboBox()
        self.left_table.currentIndexChanged.connect(lambda:self.populate_field_options(self.left_table,self.left_field))
        self.right_table.currentIndexChanged.connect(lambda:self.populate_field_options(self.right_table,self.right_field))
        for caption,control in [('Таблица A',self.left_table),('Поле A',self.left_field),
                                ('Таблица B',self.right_table),('Поле B',self.right_field)]:
            l.addWidget(QLabel(caption));l.addWidget(control)
        b=QPushButton('Добавить связь');b.clicked.connect(self.add_join);l.addWidget(b)
        self.join_list=QListWidget();l.addWidget(self.join_list,1)
        remove=QPushButton('Удалить выбранную ручную связь');remove.clicked.connect(self.remove_join)
        l.addWidget(remove);self.pages.addWidget(page)

    def build_diagram(self):
        page=QWidget();l=QVBoxLayout(page)
        toolbar=QHBoxLayout()
        toolbar.addWidget(QLabel('Перетаскивай таблицы; положение сохраняется автоматически.'))
        toolbar.addStretch()
        for name,cb in [('−',lambda:self.diagram.scale(0.8,0.8)),
                        ('+',lambda:self.diagram.scale(1.25,1.25)),
                        ('Вместить',self.fit_diagram),('Обновить',self.refresh_diagram)]:
            btn=QPushButton(name);btn.clicked.connect(cb);toolbar.addWidget(btn)
        l.addLayout(toolbar)
        self.scene=QGraphicsScene(self)
        self.diagram=QGraphicsView(self.scene)
        self.diagram.setRenderHints(self.diagram.renderHints())
        self.diagram.setDragMode(QGraphicsView.ScrollHandDrag)
        l.addWidget(self.diagram,1)
        l.addWidget(QLabel('Синие линии — внешние ключи БД; оранжевые — ручные соединения.'))
        self.pages.addWidget(page)

    def change_page(self,index):
        if index>=0:
            self.pages.setCurrentIndex(index)
            if index==4:self.refresh_diagram()

    def run_task(self,kind,fn):
        self.generation+=1
        generation=self.generation
        secret=str(self.config.get('password') or '') if self.config else ''
        self.status.setText('Загрузка метаданных…')
        def worker():
            try:
                result=fn()
                self.signals.done.emit(kind+'#'+str(generation),result)
            except Exception as e:
                # Do not display connection strings or submitted passwords.
                self.signals.failed.emit(kind+'#'+str(generation),type(e).__name__+': '+str(e).replace(secret,'***') if secret else type(e).__name__+': '+str(e))
        threading.Thread(target=worker,daemon=True,name='orbit-sql-introspection').start()

    def start_connect(self):
        cfg=dict(host=self.host.text().strip(),port=self.port.value(),database=self.database.text().strip(),
                 user=self.user.text().strip(),password=self.password.text(),sslmode=self.ssl.currentText())
        try:key=profile_key(cfg['host'],cfg['port'],cfg['database'],cfg['user'])
        except ValueError as e:return QMessageBox.warning(self,'Ошибка подключения',str(e))
        self.profile=key
        self.project=load_project(key)
        self.details={};self.available=[]
        self.config=cfg
        self.run_task('tables',lambda:discover_tables(dict(cfg)))

    def on_task_done(self,tag,result):
        kind,gen=tag.rsplit('#',1)
        if int(gen)!=self.generation:return
        self.status.setText('Подключено · '+self.config['database']+'@'+self.config['host'])
        if kind=='tables':
            self.available=result
            self.update_table_tree();self.navigation.setCurrentRow(1)
        else:
            self.details=result
            # Database catalog might have been modified while we were selecting.
            self.project['selected']=[k for k in self.project['selected'] if k in self.details]
            self.save()
            self.update_field_table_list();self.update_join_controls();self.refresh_joins()
            self.navigation.setCurrentRow(2)

    def on_task_failed(self,tag,message):
        _,gen=tag.rsplit('#',1)
        if int(gen)!=self.generation:return
        self.status.setText('Ошибка подключения или чтения метаданных')
        QMessageBox.warning(self,'SQL Explorer',message[:1000])

    def update_table_tree(self):
        self.table_tree.blockSignals(True);self.table_tree.clear()
        groups={}
        for row in self.available:
            node=groups.get(row['schema'])
            if node is None:
                node=QTreeWidgetItem([row['schema'],''])
                self.table_tree.addTopLevelItem(node);groups[row['schema']]=node
            leaf=QTreeWidgetItem([row['name'],row['comment']])
            leaf.setData(0,Qt.UserRole,row['id'])
            leaf.setFlags(leaf.flags()|Qt.ItemIsUserCheckable)
            leaf.setCheckState(0,Qt.Checked if row['id'] in self.project['selected'] else Qt.Unchecked)
            node.addChild(leaf)
        self.table_tree.expandAll();self.table_tree.blockSignals(False)
        self.update_count()

    def each_leaf(self):
        for index in range(self.table_tree.topLevelItemCount()):
            group=self.table_tree.topLevelItem(index)
            for i in range(group.childCount()): yield group.child(i)

    def filter_tables(self,needle):
        needle=needle.strip().casefold()
        for i in range(self.table_tree.topLevelItemCount()):
            root=self.table_tree.topLevelItem(i);visible=False
            for k in range(root.childCount()):
                leaf=root.child(k)
                match=needle in (root.text(0)+'.'+leaf.text(0)+' '+leaf.text(1)).casefold()
                leaf.setHidden(not match)
                visible|=match
            root.setHidden(not visible)

    def mark_visible(self,checked):
        for leaf in self.each_leaf():
            if not leaf.isHidden() and not leaf.parent().isHidden():
                leaf.setCheckState(0,Qt.Checked if checked else Qt.Unchecked)

    def table_checked(self,item,column):
        identity=item.data(0,Qt.UserRole)
        if not identity:return
        ids=set(self.project['selected'])
        if item.checkState(0)==Qt.Checked:ids.add(identity)
        else:ids.discard(identity)
        self.project['selected']=sorted(ids)
        self.save();self.update_count()

    def update_count(self):
        self.table_count.setText(f'Доступно: {len(self.available)} · в рабочем наборе: {len(self.project["selected"])}')

    def start_inspect(self):
        if not self.config:return QMessageBox.information(self,'SQL Explorer','Сначала подключись к базе')
        selected=list(self.project['selected'])
        if not selected:return QMessageBox.information(self,'SQL Explorer','Отметь хотя бы одну таблицу')
        if len(selected)>150:return QMessageBox.warning(self,'SQL Explorer','Не более 150 таблиц в одной схеме')
        cfg=dict(self.config)
        self.run_task('inspect',lambda:inspect_tables(cfg,selected))

    def update_field_table_list(self):
        self.column_tables.clear()
        for identity in self.details:
            schema,name=split_table_id(identity)
            row=QListWidgetItem(f'{schema}.{name}')
            row.setData(Qt.UserRole,identity)
            self.column_tables.addItem(row)
        if self.column_tables.count():self.column_tables.setCurrentRow(0)

    def refresh_columns(self,current,previous=None):
        self.columns.blockSignals(True);self.columns.setRowCount(0)
        if current is not None:
            identity=current.data(Qt.UserRole)
            for col in self.details.get(identity,{}).get('columns',[]):
                at=self.columns.rowCount();self.columns.insertRow(at)
                mark=('PK ' if col['pk'] else '')+('FK ' if col['fk'] else '')+('UNIQUE ' if col['unique'] else '')
                fields=[col['name'],col['type']+(' · NULL' if col['nullable'] else ''),mark,col['db_comment'],
                        self.project['notes'].get(field_note_key(identity,col['name']),'')]
                for i,value in enumerate(fields):
                    cell=QTableWidgetItem(value)
                    if i!=4:cell.setFlags(cell.flags()&~Qt.ItemIsEditable)
                    else:cell.setData(Qt.UserRole,field_note_key(identity,col['name']))
                    self.columns.setItem(at,i,cell)
        self.columns.blockSignals(False)

    def save_field_note(self,item):
        if item.column()!=4 or not self.profile:return
        key=item.data(Qt.UserRole)
        if not key:return
        note=item.text()[:2000].strip()
        if note:self.project['notes'][key]=note
        else:self.project['notes'].pop(key,None)
        self.save()

    def update_join_controls(self):
        for combo in (self.left_table,self.right_table):
            combo.clear()
            for identity in self.details:
                schema,name=split_table_id(identity)
                combo.addItem(f'{schema}.{name}',identity)
        if self.right_table.count()>1:self.right_table.setCurrentIndex(1)
        self.populate_field_options(self.left_table,self.left_field)
        self.populate_field_options(self.right_table,self.right_field)

    def populate_field_options(self,table,field):
        field.clear()
        for col in self.details.get(table.currentData(),{}).get('columns',[]):
            field.addItem(col['name'])

    def add_join(self):
        try:
            join=manual_join(self.left_table.currentData(),self.left_field.currentText(),
                             self.right_table.currentData(),self.right_field.currentText())
            if join['left']==join['right'] and join['left_column']==join['right_column']:
                raise ValueError('Связь поля с самим собой не нужна')
        except (TypeError,ValueError) as exc:
            return QMessageBox.warning(self,'Связь',str(exc))
        if join not in self.project['joins']:
            self.project['joins'].append(join);self.save();self.refresh_joins()

    def refresh_joins(self):
        self.join_list.clear()
        for j in visible_links(self.details,self.project):
            left='.'.join(split_table_id(j['left']))
            right='.'.join(split_table_id(j['right']))
            line=QListWidgetItem(f"{j['kind']}   {left}.{j['left_column']}  →  {right}.{j['right_column']}")
            if j['kind']=='manual':line.setData(Qt.UserRole,{k:j[k] for k in ('left','left_column','right','right_column')})
            self.join_list.addItem(line)

    def remove_join(self):
        row=self.join_list.currentItem()
        join=row.data(Qt.UserRole) if row else None
        if join in self.project['joins']:
            self.project['joins'].remove(join);self.save();self.refresh_joins()

    def saved_position(self,identity,point):
        if self.profile:
            self.project['positions'][identity]=[round(point.x(),1),round(point.y(),1)]
            self.save()

    def refresh_diagram(self):
        self.scene.clear();self.cards={};self.paths=[]
        import math
        for i,(identity,detail) in enumerate(self.details.items()):
            node=GraphCard(identity,detail,self.saved_position,self.refresh_paths)
            position=self.project['positions'].get(identity)
            if position is None: position=[(i%4)*340,(i//4)*560]
            self.scene.addItem(node);node.setPos(float(position[0]),float(position[1]))
            self.cards[identity]=node
        for j in visible_links(self.details,self.project):
            if j['left'] not in self.cards or j['right'] not in self.cards:continue
            shape=QGraphicsPathItem();shape.setZValue(-2)
            pen=QPen(QColor('#75BAFF' if j['kind']=='FK' else '#F7AA90'),1.8)
            if j['kind']=='manual':pen.setStyle(Qt.DashLine)
            shape.setPen(pen);self.scene.addItem(shape)
            self.paths.append((shape,self.cards[j['left']],self.cards[j['right']]))
        self.refresh_paths()
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-70,-70,70,70))

    def refresh_paths(self):
        for shape,left,right in self.paths:
            a=left.sceneBoundingRect();b=right.sceneBoundingRect()
            source=QPointF(a.right(),a.center().y()) if a.center().x()<=b.center().x() else QPointF(a.left(),a.center().y())
            target=QPointF(b.left(),b.center().y()) if a.center().x()<=b.center().x() else QPointF(b.right(),b.center().y())
            curve=QPainterPath(source)
            control=(source.x()+target.x())/2
            curve.cubicTo(control,source.y(),control,target.y(),target.x(),target.y())
            shape.setPath(curve)

    def fit_diagram(self):
        if self.cards:self.diagram.fitInView(self.scene.itemsBoundingRect().adjusted(-30,-30,30,30),Qt.KeepAspectRatio)

    def save(self):
        if self.profile:save_project(self.profile,self.project)

    def closeEvent(self,event):
        self.generation+=1
        self.config=None
        self.password.clear()
        super().closeEvent(event)
