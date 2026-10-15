"""SQL Explorer: credentials, tables, annotations, manual joins and an ER canvas."""
from __future__ import annotations
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QBrush,QColor,QPen
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QFormLayout,QLineEdit,QSpinBox,
    QComboBox,QPushButton,QLabel,QListWidget,QListWidgetItem,QTextEdit,QTableWidget,
    QTableWidgetItem,QHeaderView,QMessageBox,QInputDialog,QGraphicsView,QGraphicsScene,
    QGraphicsRectItem,QGraphicsTextItem,QGraphicsPathItem)
from PySide6.QtGui import QPainterPath
from orbit_sql_core import PostgreSQLCatalog,SQLProject,profile_key


class ERNode(QGraphicsRectItem):
    def __init__(self,window,key,fields,x,y):
        h=max(65,34+len(fields)*20)
        super().__init__(0,0,225,h)
        self.window=window;self.key=key
        self.setBrush(QBrush(QColor('#253646')))
        self.setPen(QPen(QColor('#7190a9'),1.3))
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable,True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges,True)
        self.setPos(x,y)
        title=QGraphicsTextItem(key,self);title.setDefaultTextColor(QColor('#ffffff'))
        title.setPos(8,4)
        for idx,col in enumerate(fields):
            label=QGraphicsTextItem(('🔑 ' if col.get('primary_key') else '   ')+col['name']+' · '+col['type'],self)
            label.setDefaultTextColor(QColor('#bfd5e1'));label.setPos(8,30+idx*20)

    def itemChange(self,change,value):
        if change==self.GraphicsItemChange.ItemPositionHasChanged:
            self.window.update_links()
        return super().itemChange(change,value)

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if self.window.project:
            pos=self.pos();self.window.project.position(self.key,pos.x(),pos.y())


class SQLExplorer(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle('ORBITclip · SQL Explorer')
        self.resize(1130,730)
        self.db=None;self.project=None;self.catalog=[];self.columns={};self.fks=[];self.nodes={}
        layout=QHBoxLayout(self);layout.setContentsMargins(14,14,14,14)
        left=QVBoxLayout();layout.addLayout(left,0)
        left.addWidget(QLabel('SQL Explorer'))
        self.navigation=QListWidget();self.navigation.setFixedWidth(170)
        self.pages=['Подключение','Таблицы','Поля','Связи','ER-схема']
        self.navigation.addItems(self.pages);left.addWidget(self.navigation)
        self.content=QVBoxLayout();layout.addLayout(self.content,1)
        self.title=QLabel('Подключение');self.content.addWidget(self.title)
        self.panel=QWidget();self.content.addWidget(self.panel,1)
        self.navigation.currentRowChanged.connect(self.show_page)
        self.navigation.setCurrentRow(0)

    def form(self):
        self._replace()
        form=QFormLayout(self.panel)
        self.host=QLineEdit('localhost');self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(5432)
        self.database=QLineEdit();self.user=QLineEdit();self.password=QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssl=QComboBox();self.ssl.addItems(['prefer','require','verify-full','verify-ca','disable'])
        for name,widget in [('Хост',self.host),('Порт',self.port),('База данных',self.database),
                            ('Пользователь',self.user),('Пароль',self.password),('TLS',self.ssl)]:
            form.addRow(name,widget)
        button=QPushButton('Подключиться · только метаданные');button.clicked.connect(self.connect_db)
        form.addRow(button)
        form.addRow(QLabel('Пароль используется только для подключения и никогда не сохраняется.'))

    def _replace(self):
        self.content.removeWidget(self.panel);self.panel.deleteLater()
        self.panel=QWidget();self.content.addWidget(self.panel,1)

    def connect_db(self):
        try:
            client=PostgreSQLCatalog(self.host.text(),self.port.value(),self.database.text(),
                                     self.user.text(),self.password.text(),self.ssl.currentText()).connect()
            catalog=client.tables()
            if self.db:self.db.close()
            self.db=client;self.catalog=catalog
            key=profile_key(self.host.text(),self.port.value(),self.database.text(),self.user.text())
            self.project=SQLProject(key)
            self.password.clear()
            self.navigation.setCurrentRow(1)
        except Exception as exc:
            QMessageBox.warning(self,'Ошибка подключения',str(exc)[:450])

    def show_page(self,index):
        if index<0:return
        self.title.setText(self.pages[index])
        if index==0:return self.form()
        if not self.db:
            self._replace();QVBoxLayout(self.panel).addWidget(QLabel('Сначала подключись к PostgreSQL.'))
            return
        if index==1:self.show_tables()
        elif index==2:self.show_columns()
        elif index==3:self.show_relations()
        else:self.show_graph()

    def selected_keys(self):
        return self.project.data['selected'] if self.project else []

    def show_tables(self):
        self._replace();outer=QVBoxLayout(self.panel)
        outer.addWidget(QLabel('Отметь таблицы, которые войдут в рабочую схему:'))
        self.table_list=QListWidget();outer.addWidget(self.table_list)
        active=set(self.selected_keys())
        for table in self.catalog:
            key=table['schema']+'.'+table['name']
            item=QListWidgetItem(f"{key}   ·   {table['kind']}");item.setData(Qt.ItemDataRole.UserRole,key)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in active else Qt.CheckState.Unchecked)
            self.table_list.addItem(item)
        button=QPushButton('Сохранить рабочий набор');outer.addWidget(button)
        button.clicked.connect(self.commit_tables)

    def commit_tables(self):
        keys=[self.table_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.table_list.count())
              if self.table_list.item(i).checkState()==Qt.CheckState.Checked]
        try:
            if len(keys)>150:raise ValueError('Рабочий набор ограничен 150 таблицами')
            for key in keys:
                if key not in self.columns:self.columns[key]=self.db.columns(*key.split('.',1))
            self.project.select(keys)
            self.fks=self.db.foreign_keys(keys)
            self.navigation.setCurrentRow(2)
        except Exception as exc:QMessageBox.warning(self,'Ошибка',str(exc))

    def show_columns(self):
        self._replace();outer=QVBoxLayout(self.panel)
        self.table_combo=QComboBox();self.table_combo.addItems(self.selected_keys());outer.addWidget(self.table_combo)
        self.field_table=QTableWidget(0,5)
        self.field_table.setHorizontalHeaderLabels(['Поле','Тип','NULL','PK','Комментарий'])
        self.field_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.field_table)
        self.table_combo.currentTextChanged.connect(self.refresh_columns)
        button=QPushButton('Сохранить комментарии');outer.addWidget(button)
        button.clicked.connect(self.save_columns)
        self.refresh_columns()

    def refresh_columns(self,*_):
        key=self.table_combo.currentText();columns=self.columns.get(key,[])
        self.field_table.setRowCount(len(columns))
        for row,column in enumerate(columns):
            data=[column['name'],column['type'],'Да' if column['nullable'] else 'Нет',
                  'PK' if column['primary_key'] else '',
                  self.project.data['comments'].get(key+'.'+column['name'],column['comment'])]
            for idx,value in enumerate(data):
                cell=QTableWidgetItem(str(value))
                if idx!=4:cell.setFlags(cell.flags()&~Qt.ItemFlag.ItemIsEditable)
                self.field_table.setItem(row,idx,cell)

    def save_columns(self):
        key=self.table_combo.currentText()
        for idx,column in enumerate(self.columns.get(key,[])):
            cell=self.field_table.item(idx,4)
            if cell:self.project.annotate(key,column['name'],cell.text())

    def show_relations(self):
        self._replace();outer=QVBoxLayout(self.panel)
        self.relations_text=QTextEdit();self.relations_text.setReadOnly(True);outer.addWidget(self.relations_text)
        entries=[f"{x['source_schema']}.{x['source_table']}.{x['source_column']} → {x['target_schema']}.{x['target_table']}.{x['target_column']} (FK)" for x in self.fks]
        entries += [f"{j['left']}.{j['left_column']} → {j['right']}.{j['right_column']} (ручная)" for j in self.project.data['joins']]
        self.relations_text.setPlainText('\n'.join(entries) or 'Связей пока нет')
        row=QHBoxLayout();outer.addLayout(row)
        self.left=QComboBox();self.right=QComboBox()
        self.left.addItems(self.selected_keys());self.right.addItems(self.selected_keys())
        self.lfield=QComboBox();self.rfield=QComboBox()
        for w in (self.left,self.lfield,self.right,self.rfield):row.addWidget(w)
        self.left.currentTextChanged.connect(lambda *_:self.fill_fields(self.left,self.lfield))
        self.right.currentTextChanged.connect(lambda *_:self.fill_fields(self.right,self.rfield))
        self.fill_fields(self.left,self.lfield);self.fill_fields(self.right,self.rfield)
        button=QPushButton('Добавить связь');outer.addWidget(button);button.clicked.connect(self.add_relation)

    def fill_fields(self,tables,field):
        field.clear();field.addItems([c['name'] for c in self.columns.get(tables.currentText(),[])])

    def add_relation(self):
        try:
            self.project.relation(self.left.currentText(),self.lfield.currentText(),
                                  self.right.currentText(),self.rfield.currentText())
            self.show_relations()
        except Exception as exc:QMessageBox.warning(self,'Связь',str(exc))

    def show_graph(self):
        self._replace();outer=QVBoxLayout(self.panel)
        outer.addWidget(QLabel('Перетаскивай таблицы мышью. Расположение сохранится локально.'))
        self.scene=QGraphicsScene();self.nodes={}
        for index,key in enumerate(self.selected_keys()):
            pos=self.project.data['positions'].get(key,[(index%4)*270,(index//4)*220])
            node=ERNode(self,key,self.columns.get(key,[]),*pos)
            self.scene.addItem(node);self.nodes[key]=node
        self.graph=QGraphicsView(self.scene)
        outer.addWidget(self.graph)
        self.update_links()

    def update_links(self):
        if not hasattr(self,'scene') or not self.scene:return
        for item in list(self.scene.items()):
            if isinstance(item,QGraphicsPathItem):self.scene.removeItem(item)
        links=[(f"{x['source_schema']}.{x['source_table']}",f"{x['target_schema']}.{x['target_table']}") for x in self.fks]
        links.extend((x['left'],x['right']) for x in self.project.data['joins'])
        for left,right in links:
            if left not in self.nodes or right not in self.nodes:continue
            a=self.nodes[left].sceneBoundingRect().center();b=self.nodes[right].sceneBoundingRect().center()
            path=QPainterPath(a);d=(b.x()-a.x())*.48
            path.cubicTo(QPointF(a.x()+d,a.y()),QPointF(b.x()-d,b.y()),b)
            edge=QGraphicsPathItem(path)
            edge.setPen(QPen(QColor('#86b5ca'),1.4));edge.setZValue(-1)
            self.scene.addItem(edge)

    def closeEvent(self,event):
        if self.db:self.db.close();self.db=None
        super().closeEvent(event)
