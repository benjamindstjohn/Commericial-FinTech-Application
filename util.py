import asyncio
from datetime import datetime
from random import choices
from typing import Literal, Union
import pandas as pd


class Pane:
    def __init__(self, window):
        from lightweight_charts import Window
        self.win: Window = window
        self.run_script = window.run_script
        if hasattr(self, 'id'):
            return
        self.id = Window._id_gen.generate()


class IDGen(list):
    ascii = 'abcdefghijklmnopqrstuvwxyz'

    def generate(self):
        var = ''.join(choices(self.ascii, k=8))
        if var not in self:
            self.append(var)
            return f'window.{var}'
        self.generate()


def parse_event_message(window, string):
    name, args = string.split('_~_')
    args = args.split(';;;')
    func = window.handlers[name]
    return func, args


def jbool(b: bool): return 'true' if b is True else 'false' if b is False else None


LINE_STYLE = Literal['solid', 'dotted', 'dashed', 'large_dashed', 'sparse_dotted']

MARKER_POSITION = Literal['above', 'below', 'inside']

MARKER_SHAPE = Literal['arrow_up', 'arrow_down', 'circle', 'square']

CROSSHAIR_MODE = Literal['normal', 'magnet']

PRICE_SCALE_MODE = Literal['normal', 'logarithmic', 'percentage', 'index100']

TIME = Union[datetime, pd.Timestamp, str]

NUM = Union[float, int]

FLOAT = Literal['left', 'right', 'top', 'bottom']


def line_style(line: LINE_STYLE):
    js = 'LightweightCharts.LineStyle.'
    return js+line[:line.index('_')].title() + line[line.index('_') + 1:].title() if '_' in line else js+line.title()


def crosshair_mode(mode: CROSSHAIR_MODE):
    return f'LightweightCharts.CrosshairMode.{mode.title()}' if mode else None


def price_scale_mode(mode: PRICE_SCALE_MODE):
    return f"LightweightCharts.PriceScaleMode.{'IndexedTo100' if mode == 'index100' else mode.title() if mode else None}"


def marker_shape(shape: MARKER_SHAPE):
    return shape[:shape.index('_')]+shape[shape.index('_')+1:].title() if '_' in shape else shape.title()


def marker_position(p: MARKER_POSITION):
    return {
        'above': 'aboveBar',
        'below': 'belowBar',
        'inside': 'inBar',
        None: None,
    }[p]


class Emitter:
    def __init__(self):
        self._callable = None

    def __iadd__(self, other):
        self._callable = other
        return self

    def _emit(self, *args):
        self._callable(*args) if self._callable else None


class JSEmitter:
    def __init__(self, chart, name, on_iadd, wrapper=None):
        self._on_iadd = on_iadd
        self._chart = chart
        self._name = name
        self._wrapper = wrapper

    def __iadd__(self, other):
        def final_wrapper(*arg):
            other(self._chart, *arg) if not self._wrapper else self._wrapper(other, self._chart, *arg)
        async def final_async_wrapper(*arg):
            await other(self._chart, *arg) if not self._wrapper else await self._wrapper(other, self._chart, *arg)

        self._chart.win.handlers[self._name] = final_async_wrapper if asyncio.iscoroutinefunction(other) else final_wrapper
        self._on_iadd(other)
        return self


class Events:
    def __init__(self, chart):
        self.new_bar = Emitter()
        from lightweight_charts.abstract import JS
        self.search = JSEmitter(chart, f'search{chart.id}',
            lambda o: chart.run_script(f'''
            {JS['callback']}
            makeSpinner({chart.id})
            {chart.id}.search = makeSearchBox({chart.id})
            ''')
        )
        self.range_change = JSEmitter(chart, f'range_change{chart.id}',
            lambda o: chart.run_script(f'''
            let checkLogicalRange = (logical) => {{
                {chart.id}.chart.timeScale().unsubscribeVisibleLogicalRangeChange(checkLogicalRange)
                
                let barsInfo = {chart.id}.series.barsInLogicalRange(logical)
                if (barsInfo) window.callbackFunction(`range_change{chart.id}_~_${{barsInfo.barsBefore}};;;${{barsInfo.barsAfter}}`)
                    
                setTimeout(() => {chart.id}.chart.timeScale().subscribeVisibleLogicalRangeChange(checkLogicalRange), 50)
            }}
            {chart.id}.chart.timeScale().subscribeVisibleLogicalRangeChange(checkLogicalRange)
            '''),
            wrapper=lambda o, c, *arg: o(c, *[float(a) for a in arg])
        )

import asyncio

from .util import parse_event_message
from lightweight_charts import abstract

try:
    import wx.html2
except ImportError:
    wx = None

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    from PyQt5.QtWebChannel import QWebChannel
    from PyQt5.QtCore import QObject, pyqtSlot as Slot
except ImportError:
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtCore import QObject, Slot
    except ImportError:
        QWebEngineView = None

if QWebEngineView:
    class Bridge(QObject):
        def __init__(self, chart):
            super().__init__()
            self.chart = chart

        @Slot(str)
        def callback(self, message):
            emit_callback(self.chart, message)

try:
    from streamlit.components.v1 import html
except ImportError:
    html = None

try:
    from IPython.display import HTML, display
except ImportError:
    HTML = None


def emit_callback(window, string):
    func, args = parse_event_message(window, string)
    asyncio.create_task(func(*args)) if asyncio.iscoroutinefunction(func) else func(*args)


class WxChart(abstract.AbstractChart):
    def __init__(self, parent, inner_width: float = 1.0, inner_height: float = 1.0,
                 scale_candles_only: bool = False, toolbox: bool = False):
        if wx is None:
            raise ModuleNotFoundError('wx.html2 was not found, and must be installed to use WxChart.')
        self.webview: wx.html2.WebView = wx.html2.WebView.New(parent)
        super().__init__(abstract.Window(self.webview.RunScript, 'window.wx_msg.postMessage.bind(window.wx_msg)'),
                         inner_width, inner_height, scale_candles_only, toolbox)

        self.webview.Bind(wx.html2.EVT_WEBVIEW_LOADED, lambda e: wx.CallLater(500, self.win.on_js_load))
        self.webview.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, lambda e: emit_callback(self, e.GetString()))
        self.webview.AddScriptMessageHandler('wx_msg')
        self.webview.SetPage(abstract.TEMPLATE, '')
        self.webview.AddUserScript(abstract.JS['toolbox']) if toolbox else None

    def get_webview(self): return self.webview


class QtChart(abstract.AbstractChart):
    def __init__(self, widget=None, inner_width: float = 1.0, inner_height: float = 1.0,
                 scale_candles_only: bool = False, toolbox: bool = False):
        if QWebEngineView is None:
            raise ModuleNotFoundError('QWebEngineView was not found, and must be installed to use QtChart.')
        self.webview = QWebEngineView(widget)
        super().__init__(abstract.Window(self.webview.page().runJavaScript, 'window.pythonObject.callback'),
                         inner_width, inner_height, scale_candles_only, toolbox)

        self.web_channel = QWebChannel()
        self.bridge = Bridge(self)
        self.web_channel.registerObject('bridge', self.bridge)
        self.webview.page().setWebChannel(self.web_channel)
        self.webview.loadFinished.connect(self.win.on_js_load)
        self._html = f'''
        {abstract.TEMPLATE[:85]}
        <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
        <script>
        var bridge = new QWebChannel(qt.webChannelTransport, function(channel) {{
            var pythonObject = channel.objects.bridge;
            window.pythonObject = pythonObject
        }});
        </script>
        {abstract.TEMPLATE[85:]}
        '''
        self.webview.page().setHtml(self._html)

    def get_webview(self): return self.webview


class StaticLWC(abstract.AbstractChart):
    def __init__(self, width=None, height=None, inner_width=1, inner_height=1,
                 scale_candles_only: bool = False, toolbox=False, autosize=True):
        self._html = abstract.TEMPLATE.replace('</script>\n</body>\n</html>', '')
        super().__init__(abstract.Window(run_script=self.run_script), inner_width, inner_height,
                         scale_candles_only, toolbox, autosize)
        self.width = width
        self.height = height

    def run_script(self, script, run_last=False):
        if run_last:
            self.win.final_scripts.append(script)
        else:
            self._html += '\n' + script

    def load(self):
        if self.win.loaded:
            return
        self.win.loaded = True
        for script in self.win.final_scripts:
            self._html += '\n' + script
        self._load()

    def _load(self): pass


class StreamlitChart(StaticLWC):
    def __init__(self, width=None, height=None, inner_width=1, inner_height=1, scale_candles_only: bool = False, toolbox: bool = False):
        super().__init__(width, height, inner_width, inner_height, scale_candles_only, toolbox)

    def _load(self):
        if html is None:
            raise ModuleNotFoundError('streamlit.components.v1.html was not found, and must be installed to use StreamlitChart.')
        html(f'{self._html}</script></body></html>', width=self.width, height=self.height)


class JupyterChart(StaticLWC):
    def __init__(self, width: int = 800, height=350, inner_width=1, inner_height=1, scale_candles_only: bool = False, toolbox: bool = False):
        super().__init__(width, height, inner_width, inner_height, scale_candles_only, toolbox, False)

        self.run_script(f'''
            for (var i = 0; i < document.getElementsByClassName("tv-lightweight-charts").length; i++) {{
                    var element = document.getElementsByClassName("tv-lightweight-charts")[i];
                    element.style.overflow = "visible"
                }}
            document.getElementById('wrapper').style.overflow = 'hidden'
            document.getElementById('wrapper').style.borderRadius = '10px'
            document.getElementById('wrapper').style.width = '{self.width}px'
            document.getElementById('wrapper').style.height = '100%'
            ''')
        self.run_script(f'{self.id}.chart.resize({width}, {height})')

    def _load(self):
        if HTML is None:
            raise ModuleNotFoundError('IPython.display.HTML was not found, and must be installed to use JupyterChart.')
        display(HTML(f'{self._html}</script></body></html>'))