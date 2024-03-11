import os, io, time, asyncio, vlc, ctypes, functools, random, threading, platform, sys
from PyQt5.QtWidgets import QWidget

#from asyncio import ensure_future, get_event_loop
from dataclasses import dataclass
from typing import List

from pyipv8.ipv8.community import DEFAULT_MAX_PEERS, Community
from pyipv8.ipv8.configuration import ConfigBuilder, Strategy, WalkerDefinition, BootstrapperDefinition, Bootstrapper, default_bootstrap_defs
from pyipv8.ipv8.lazy_community import lazy_wrapper, lazy_wrapper_unsigned
from pyipv8.ipv8.messaging.payload_dataclass import overwrite_dataclass, type_from_format
from pyipv8.ipv8_service import IPv8, Peer

from PyQt5 import QtWidgets, QtGui, QtCore

import random
random.seed()

ParallelDownloads = 350
PieceSize = 1440
BeginSize = 1024 * 1024 * 16
Timeout = 0.6
TryNum = 8
WaitDelay = 600
Delay1 = 1300
Delay2 = 6000


u16_t = type_from_format('H')
u32_t = type_from_format('I')
u64_t = type_from_format('Q')
i64_t = type_from_format('q')


dataclass = overwrite_dataclass(dataclass)
@dataclass(msg_id=1)
class InfoRequest:
	id:		u32_t
	hash:	u32_t
@dataclass(msg_id=2)
class InfoResponse:
	id:		u32_t
	size:	u64_t
	name:	str
@dataclass(msg_id=3)
class DataRequest:
	id:		u32_t
	hash:	u32_t
	offset: u64_t
	count:	u16_t
@dataclass(msg_id=4)
class DataResponse:
	id:		u32_t
	data:	bytes
@dataclass(msg_id=5)
class PosInfo:
	hash:		u32_t
	clock:		u32_t
	time:		u64_t
	speed:		u16_t
	peer_mid:	bytes

class Fileable:
	def __init__(self):
		self.event = threading.Event()
		self.size = -1
		self.name = ''
class Downloadable:
	def __init__(self):
		self.event = threading.Event()
		self.data: bytes = None


class MyIpv8(IPv8):
	def work(self, type, key_path: str, event: threading.Event):
		async def task(self):
			builder = ConfigBuilder().clear_keys().clear_overlays()
			builder.add_key('my peer', 'curve25519', key_path)
			builder.add_overlay('Community', 'my peer',
				[WalkerDefinition(Strategy.RandomWalk, 10, {'timeout': 3.0})],
				#[BootstrapperDefinition(Bootstrapper.UDPBroadcastBootstrapper, {})],
				default_bootstrap_defs,
				{}, [('started',)])
			super().__init__(builder.finalize(), extra_communities={'Community': type})
			await self.start()
			event.set()

		self.loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self.loop)
		self.loop.create_task(task(self))
		self.loop.run_forever()

	def __init__(self, type, key_path: str):
		event = threading.Event()
		self.thr = threading.Thread(target=self.work, args=(type, key_path, event))
		self.thr.start()
		event.wait()

	def stop(self):
		asyncio.run_coroutine_threadsafe(super().stop(), self.loop)
		self.thr.join()

class PlayerCommunity(Community):
	community_id = bytes([249,163,199,83,219,30,60,31,113,43,227,160,232,240,20,244,2,164,159,28])
	def started(self):
		self.add_message_handler(1, self.info_req)
		self.add_message_handler(2, self.info_resp)
		self.add_message_handler(3, self.data_req)
		self.add_message_handler(4, self.data_resp)
		self.add_message_handler(5, self.on_info)
		self.loop = asyncio.get_event_loop()
		self.counter = random.randint(1, 500000000)
		self.waiting = {}
		self.file = None
		self.state_cb = None

		c = 1
		async def info_task():
			nonlocal c
			print(self.my_peer, [str(peer) for peer in self.get_peers()], c)
			c += 1
		self.register_task('info', info_task, delay=5, interval=5)

		self.endpoint

	def open_file(self, path: str):
		if self.file:
			self.file.close()
		self.file = open(path, 'rb')
		self.file_size = os.path.getsize(path)
		_, self.file_name = os.path.split(path)
		self.file_hash = self.counter
		self.counter += 1

	def create_id(self, range=1):
		c = self.counter
		self.counter += range
		return c

	def find_peer(self, peer_mid):
		for peer in self.get_peers():
			if peer.mid == peer_mid:
				return peer
		return None
	
	def request_file_info(self, peer: Peer, hash: int):
		c = self.create_id()
		info = Fileable()
		self.waiting[c] = info
		async def task():
			for _ in range(TryNum):
				self.ez_send(peer, InfoRequest(c, hash))
				await asyncio.sleep(Timeout)
				if info.event.is_set():
					return
			info.event.set()
			self.waiting.pop(c)
		asyncio.run_coroutine_threadsafe(task(), self.loop)
		return info
	@lazy_wrapper(InfoRequest)
	def info_req(self, peer, request: InfoRequest):
		size = self.file_size if request.hash == self.file_hash else 0
		name = self.file_name if request.hash == self.file_hash else ''
		self.ez_send(peer, InfoResponse(request.id, size, name))
	@lazy_wrapper(InfoResponse)
	def info_resp(self, peer: Peer, response: InfoResponse):
		if response.id in self.waiting.keys():
			info = self.waiting[response.id]
			if isinstance(info, Fileable):
				info.size = response.size
				info.name = response.name
				info.event.set()

	def request_data(self, peer: Peer, hash: int, offset: int, count: int):
		id = self.create_id(count)
		infos = []
		for c in range(id, id + count):
			info = Downloadable()
			infos.append((c, info))
			self.waiting[c] = info
		async def task(infos: list):
			self.ez_send(peer, DataRequest(id, hash, offset, count), sig=False)
			for _ in range(TryNum):
				await asyncio.sleep(Timeout)
				next_infos = []
				for c, info in infos:
					if not info.event.is_set():
						self.ez_send(peer, DataRequest(c, hash, offset + (c-id) * PieceSize, 1), sig=False)
						next_infos.append((c, info))
				if not len(next_infos):
					return
				infos = next_infos
			for c, info in infos:
				info.data = bytes()
				info.event.set()
				self.waiting.pop(c)
		asyncio.run_coroutine_threadsafe(task(infos), self.loop)
		return infos
	@lazy_wrapper_unsigned(DataRequest)
	def data_req(self, address, request: DataRequest):
		self.file.seek(request.offset if request.hash == self.file_hash else self.file_size)
		for id in range(request.id, request.id + request.count):
			data = self.file.read(PieceSize)
			response = DataResponse(id, data)
			self._ez_senda(address, response, sig=False)
		#async def task():
		#	self.file.seek(request.offset if request.hash == self.file_hash else self.file_size)
		#	for id in range(request.id, request.id + request.count):
		#		data = self.file.read(PieceSize)
		#		response = DataResponse(id, data)
		#		if random.random() < 0.985:
		#			self._ez_senda(address, response, sig=False)
		#self.register_anonymous_task('req', task, delay=0.2)
	@lazy_wrapper_unsigned(DataResponse)
	def data_resp(self, address, response: DataResponse):
		if response.id in self.waiting.keys():
			info = self.waiting.pop(response.id)
			if isinstance(info, Downloadable):
				info.data = response.data
				info.event.set()
	
	def send_state(self, state: PosInfo):
		async def task():
			for peer in self.get_peers():
				self.ez_send(peer, state, sig=False)
		asyncio.run_coroutine_threadsafe(task(), self.loop)
	@lazy_wrapper_unsigned(PosInfo)
	def on_info(self, peer: Peer, info: PosInfo):
		if self.state_cb:
			self.state_cb(info)

class Deque:
	def __init__(self, max_size: int):
		self.data = [None] * max_size
		self.put_index = 0
		self.get_index = 0
		self.size = 0

	def put(self, item):
		self.data[self.put_index] = item
		self.put_index += 1
		if self.put_index == len(self.data):
			self.put_index = 0
		self.size += 1
	def get(self):
		item = self.data[self.get_index]
		self.get_index += 1
		if self.get_index == len(self.data):
			self.get_index = 0
		self.size -= 1
		return item
	
	def rput(self, item):
		if self.get_index == 0:
			self.get_index = len(self.data)
		self.get_index -= 1
		self.data[self.get_index] = item
		self.size += 1
	def rget(self):
		if self.put_index == 0:
			self.put_index = len(self.data)
		self.put_index -= 1
		self.size -= 1
		return self.data[self.put_index]

class VlcReader:
	def request_pieces(self):
		count = ParallelDownloads - self.queue.size
		if count <= 0:
			return
		pieces = self.community.request_data(self.peer, self.hash, self.rpos, count)
		for c, piece in pieces:
			self.queue.put(piece)
		self.rpos += len(pieces) * PieceSize
	def get_piece(self):
		piece: Downloadable = self.queue.get()
		piece.event.wait()
		return piece.data
	def clear_queue(self):
		while self.queue.size > 0:
			self.queue.get().event.set()

	inst = None
	def __init__(self, community: PlayerCommunity, peer: Peer, hash: int):
		VlcReader.inst = self
		self.community = community
		self.peer = peer
		self.hash = hash

		file_info = community.request_file_info(peer, hash)
		file_info.event.wait()
		self.size = file_info.size
		self.name = file_info.name
		begin_size = min(BeginSize, self.size)
		begin_size += PieceSize - begin_size % PieceSize

		self.rpos = 0
		self.wpos = 0
		self.queue = Deque(ParallelDownloads)
		self.request_pieces()
		
		self.last_piece = None
		self.begin_buffer = bytearray(begin_size)
		self.read_func = self.read_begin
		self.save = 1
		
	@staticmethod
	@vlc.CallbackDecorators.MediaOpenCb
	def open(opaque, data, size):
		self = VlcReader.inst
		data.contents.value = opaque
		size.value = self.size
		
		index = 0
		while True:
			piece = self.get_piece()
			if len(piece) <= 0:
				return -1
			self.request_pieces()
			next_index = index + len(piece)
			if next_index > len(self.begin_buffer):
				return -1
			self.begin_buffer[index:next_index] = piece
			if next_index == len(self.begin_buffer):
				break
			index = next_index

		self.last_piece = self.get_piece()
		return 0

	@staticmethod
	def read_begin(opaque, buffer, size):
		self = VlcReader.inst
		next_pos = self.wpos + min(1024*1024, size)
		if next_pos >= len(self.begin_buffer):
			next_pos = len(self.begin_buffer)
			self.read_func = self.read_middle
		index = 0
		for byte in self.begin_buffer[self.wpos:next_pos]:
			buffer[index] = byte
			index += 1
		return index
	@staticmethod
	def read_middle(opaque, buffer, size):
		self = VlcReader.inst
		size = min(size, 1024 * 128)
		index = 0
		while size - index >= len(self.last_piece):
			if len(self.last_piece) <= 0:
				return index
			for byte in self.last_piece:
				buffer[index] = byte
				index += 1
			self.last_piece = self.get_piece()
			#if self.queue.size < ParallelDownloads - 100:
			#	self.request_pieces()
		self.request_pieces()
		length = size - index
		for piece_index in range(length):
			buffer[index] = self.last_piece[piece_index]
			index += 1
		self.last_piece = self.last_piece[length:]
		return index
	@staticmethod
	@vlc.CallbackDecorators.MediaReadCb
	def read(opaque, buffer, size):
		self = VlcReader.inst
		result = self.read_func(opaque, buffer, size)
		self.wpos += result
		return result

	@staticmethod
	@vlc.CallbackDecorators.MediaSeekCb
	def seek(opaque, offset):
		self = VlcReader.inst
		def update_queue(new_pos: int):
			if self.wpos == new_pos:
				return
			self.rpos = new_pos
			if self.save == 1:# and self.wpos == len(self.begin_buffer):
				item = Downloadable()
				item.data = self.last_piece
				item.event.set()
				self.queue.rput(item)
				self.save = self.queue
				self.queue = Deque(ParallelDownloads)
			else:
				self.clear_queue()
			if isinstance(self.save, Deque) and new_pos == len(self.begin_buffer):
				self.queue = self.save
				self.save = None
			else:
				self.request_pieces()
			self.last_piece = self.get_piece()

		if offset < 0 or offset > self.size:
			return -1
		
		if offset < len(self.begin_buffer):
			if self.read_func == self.read_middle:
				self.read_func = self.read_begin
				update_queue(len(self.begin_buffer))
		else:
			if self.read_func == self.read_begin:
				self.read_func = self.read_middle
				self.wpos = len(self.begin_buffer)
			update_queue(offset)
		self.wpos = offset
		return 0

	@staticmethod
	@vlc.CallbackDecorators.MediaCloseCb
	def close(opaque):
		VlcReader.inst.clear_queue()

class PlayerSlider(QtWidgets.QSlider):
	sliderSet = QtCore.pyqtSignal()
	def __init__(self, parent = None):
		super().__init__(QtCore.Qt.Horizontal, parent)
		self.pressed = False
		self.sliderPressed.connect(self.on_press)
	def on_press(self):
		self.pressed = True
	def mouseReleaseEvent(self, e):
		if e.button() == QtCore.Qt.LeftButton and not self.pressed:
			e.accept()
			x = e.pos().x()
			value = int((self.maximum() - self.minimum()) * x / self.width()) + self.minimum()
			self.setValue(value)
			self.sliderSet.emit()
		else:
			self.pressed = False
			super().mouseReleaseEvent(e)

class PlayerTracks:
	def __init__(self, tracks):
		self.ids = []
		self.names = []
		for id, name in tracks:
			if id >= 0:
				self.ids.append(id)
				self.names.append(name.decode())
	def next(self, cur_id):
		for i, id in enumerate(self.ids):
			if cur_id == id:
				cur_id = i
				break
		cur_id += 1
		if cur_id >= len(self.names):
			cur_id = 0
		return self.ids[cur_id], self.names[cur_id]
	def prev(self, cur_id):
		for i, id in enumerate(self.ids):
			if cur_id == id:
				cur_id = i
				break
		cur_id -= 1
		if cur_id < 0:
			cur_id = len(self.names) - 1
		return self.ids[cur_id], self.names[cur_id]

class Player(QtWidgets.QMainWindow):
	def time2str(self, ms):
		s = round(ms * 0.001)
		m, s = divmod(s, 60)
		h, m = divmod(m, 60)
		return (f'{h}:' if h else '') + '{:02}:{:02}'.format(m, s)
	def resource_path(self, relative_path):
		base_path=getattr(sys,'_MEIPASS',os.path.dirname(os.path.abspath(__file__)))
		return os.path.join(base_path, relative_path)
	
	state_signal = QtCore.pyqtSignal()
	wait_signal = QtCore.pyqtSignal(int)
	info_signal = QtCore.pyqtSignal()
	buffer_signal = QtCore.pyqtSignal(bool)
	on_state_signal = QtCore.pyqtSignal(PosInfo)
	def __init__(self, key_path):
		QtWidgets.QMainWindow.__init__(self, None)
		self.setWindowIcon(QtGui.QIcon(self.resource_path('goose.ico')))

		self.instance: vlc.Instance = vlc.Instance()
		player: vlc.MediaPlayer = self.instance.media_player_new()
		self.player: vlc.MediaPlayer = player
		self.player.video_set_scale(1)
		self.player.video_set_mouse_input(False)
		self.player.video_set_key_input(False)
		self.buffering = False
		self.buffer_signal.connect(self.set_buffering)

		events = self.player.event_manager()
		events.event_attach(vlc.EventType.MediaPlayerPlaying,			self.on_play)
		events.event_attach(vlc.EventType.MediaPlayerPaused,			self.on_pause)
		events.event_attach(vlc.EventType.MediaPlayerStopped,			self.on_stop)
		events.event_attach(vlc.EventType.MediaPlayerPositionChanged,	self.on_position)
		events.event_attach(vlc.EventType.MediaPlayerTimeChanged,		self.on_time)
		events.event_attach(vlc.EventType.MediaPlayerBuffering,			self.on_buffering)
		
		self.widget = QtWidgets.QWidget(self)
		self.setCentralWidget(self.widget)
		self.init_menu()
		self.init_layout()
		self.init_info()

		self.clock = 0
		self.ipv8 = MyIpv8(PlayerCommunity, key_path)
		community: PlayerCommunity = self.ipv8.get_overlay(PlayerCommunity)
		self.community = community
		self.on_state_signal.connect(self.on_state)
		self.community.state_cb = self.on_state_signal.emit

		self.state_timer = QtCore.QTimer(self)
		self.state_timer.setInterval(2000)
		self.state_timer.timeout.connect(lambda: self.send_state(self.player.is_playing()))
		self.state_signal.connect(self.state_timer.start)

		def after_wait():
			self.update_state(True)
			self.player.play()
		self.wait_timer = QtCore.QTimer(self)
		self.wait_timer.setSingleShot(True)
		self.wait_timer.timeout.connect(after_wait)
		self.wait_signal.connect(self.wait_timer.start)

		self.cursor_timer = QtCore.QTimer(self)
		self.cursor_timer.setInterval(4000)
		self.cursor_timer.setSingleShot(True)
		self.cursor_timer.timeout.connect(lambda: self.setCursor(QtCore.Qt.CursorShape.BlankCursor))
		self.installEventFilter(self)

		self.on_stop(None)
	
	def closeEvent(self, event):
		self.player.stop()
		self.ipv8.stop()

	def get_speed(self):
		return round(self.player.get_rate() * 100)
	def set_speed(self, speed):
		speed *= 0.01
		if self.player.set_rate(speed) == 0:
			self.show_info(f'Speed: {speed:.2f}')

	def init_menu(self):
		menu_bar = self.menuBar()

		open_action = QtWidgets.QAction("Load Video", self)
		close_action = QtWidgets.QAction("Close App", self)
		open_action.triggered.connect(self.open_dialog)
		close_action.triggered.connect(self.close)
		file_menu = menu_bar.addMenu("File")
		file_menu.addAction(open_action)
		file_menu.addAction(close_action)

		action = QtWidgets.QAction("Crop to fit", self, checkable=True)
		def set_crop():
			if action.isChecked():
				self.update_scale()
			else:
				self.player.video_set_scale(0)
		action.triggered.connect(set_crop)
		action.setChecked(True)
		menu = menu_bar.addMenu("Video")
		menu.addAction(action)
	def init_video_frame(self):
		if platform.system() == "Darwin": # for MacOS
			self.videoframe = QtWidgets.QMacCocoaViewContainer(0)
		else:
			self.videoframe = QtWidgets.QFrame()
		palette = self.videoframe.palette()
		palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0))
		self.videoframe.setPalette(palette)
		self.videoframe.setAutoFillBackground(True)
	def init_loading(self):
		self.loading = QtWidgets.QLabel()
		self.loading.setStyleSheet("background:white;")
		self.loading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
		movie = QtGui.QMovie(self.resource_path('loading.gif'), b'GIF')
		self.loading.setMovie(movie)
		self.loading.movie().start()
		movie.setScaledSize(self.loading.sizeHint() / 2)
	def init_controls(self):
		self.controls = QtWidgets.QWidget()

		self.time0 = QtWidgets.QLabel()
		self.time1 = QtWidgets.QLabel()
		self.pos_slider = PlayerSlider()
		def move_position():
			self.time0.setText(self.time2str(self.pos_slider.value() / 65536.0 * self.player.get_length()))
		def on_position0():
			self.was_playing = self.player.is_playing()
			if self.was_playing:
				self.player.pause()
		def on_position1():
			self.player.set_position(self.pos_slider.value() / 65536.0)
			if self.was_playing:
				self.player.play()
			self.update_state(self.was_playing)
		def on_position():
			self.player.set_position(self.pos_slider.value() / 65536.0)
			self.update_state(self.player.is_playing())
		self.pos_slider.setToolTip('Position')
		self.pos_slider.setMaximum(65536)
		self.pos_slider.sliderMoved.connect(move_position)
		self.pos_slider.sliderPressed.connect(on_position0)
		self.pos_slider.sliderReleased.connect(on_position1)
		self.pos_slider.sliderSet.connect(on_position)

		self.play = QtWidgets.QPushButton()
		self.play.clicked.connect(self.play_pause)
		self.stop = QtWidgets.QPushButton('Stop')
		self.stop.clicked.connect(self.player.stop)
		self.vol_lider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
		self.vol_lider.setMaximum(100)
		self.vol_lider.setValue(100)
		self.vol_lider.setToolTip('Volume')
		self.vol_lider.valueChanged.connect(self.player.audio_set_volume)
		self.vol_lider.setTickInterval(25)

		line1 = QtWidgets.QHBoxLayout()
		line1.addWidget(self.time0)
		line1.addWidget(self.pos_slider, 1)
		line1.addWidget(self.time1)

		line2 = QtWidgets.QHBoxLayout()
		line2.addWidget(self.play)
		line2.addWidget(self.stop)
		line2.addStretch(1)
		line2.addWidget(self.vol_lider)

		layout = QtWidgets.QVBoxLayout(self.controls)
		layout.addLayout(line1)
		layout.addLayout(line2)
	def init_layout(self):
		self.init_video_frame()
		self.init_controls()
		self.init_loading()
		layout = QtWidgets.QVBoxLayout(self.widget)
		layout.setContentsMargins(0,0,0,0)
		layout.addWidget(self.videoframe, 1)
		layout.addWidget(self.loading, 1)
		layout.addWidget(self.controls)
	def init_info(self):
		self.infolabel = QtWidgets.QLabel(self.widget)
		self.infolabel.move(25, 25)
		pallete = self.infolabel.palette()
		pallete.setColor(self.infolabel.backgroundRole(), QtGui.QColor(4, 4, 4, 64))
		pallete.setColor(self.infolabel.foregroundRole(), QtGui.QColor(255, 255, 255))
		self.infolabel.setPalette(pallete)
		font = self.infolabel.font()
		font.setPointSize(32)
		self.infolabel.setFont(font)
		self.infolabel.resize(self.infolabel.sizeHint())
		self.infolabel.hide()

		self.info_timer = QtCore.QTimer(self)
		self.info_timer.setInterval(1300)
		self.info_timer.setSingleShot(True)
		self.info_timer.timeout.connect(self.infolabel.hide)
		self.info_signal.connect(self.info_timer.start)
	def show_info(self, text: str):
		self.infolabel.setText(text)
		self.infolabel.resize(self.infolabel.sizeHint())
		self.infolabel.show()
		self.info_signal.emit()

	def play_pause(self):
		if self.player.is_playing():
			self.player.pause()
			self.update_state(False)
		else:
			if self.player.play() == -1:
				self.open_dialog()
			else:
				self.update_state(True)

	def on_play(self, event):
		self.play.setText('Pause')
		if self.audio_tracks == None:
			self.audio_tracks = PlayerTracks(self.player.audio_get_track_description())
	def on_pause(self, event):
		self.play.setText('Play')
	def on_stop(self, event):
		self.play.setText('Play')
		self.videoframe.update()
		self.pos_slider.setValue(0)
		self.time0.setText('')
		self.time1.setText('')
		self.setWindowTitle('Mirror')
		self.peer: Peer = None
		self.hash = 0
		self.audio_tracks = None

		self.videoframe.show()
		self.loading.movie().stop()
		self.loading.hide()
	def on_position(self, event):
		self.pos_slider.setValue(int(event.u.new_position * 65536))
	def on_time(self, event):
		self.time0.setText(self.time2str(event.u.new_time))
	def on_buffering(self, event):
		self.buffer_signal.emit(event.u.new_cache < 100.0)
	def on_duration(self, event):
		self.time1.setText(self.time2str(event.u.new_duration))
		self.update_state(self.player.is_playing())
	def on_parsed(self, event:vlc.Event):
		if event.u.new_status == vlc.MediaParsedStatus.done:
			title = self.player.get_media().get_meta(0)
			if 'imem' not in title:
				self.setWindowTitle(title)

	def set_buffering(self, buffering: bool):
		if buffering:
			if not self.videoframe.isHidden():
				self.videoframe.hide()
				self.loading.movie().start()
				self.loading.show()
		else:
			self.videoframe.show()
			self.loading.movie().stop()
			self.loading.hide()
			if self.player.video_get_scale():
				self.update_scale()
	def go_fullscreen(self):
		self.menuBar().hide()
		self.controls.hide()
		self.setWindowState(QtCore.Qt.WindowFullScreen)
	def esc_fullscreen(self):
		self.menuBar().show()
		self.controls.show()
		self.setWindowState(QtCore.Qt.WindowNoState)
	def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
		if event.button() == QtCore.Qt.LeftButton:
			if self.windowState() != QtCore.Qt.WindowFullScreen:
				self.go_fullscreen()
			else:
				self.esc_fullscreen()
	def keyPressEvent(self, event: QtGui.QKeyEvent):
		def add_speed(add):
			speed = self.get_speed() + add
			speed = max(25, speed)
			speed = min(200, speed)
			self.set_speed(speed)
			self.update_state(self.player.is_playing())

		if event.key() == QtCore.Qt.Key.Key_Space or \
			event.key() == QtCore.Qt.Key.Key_MediaTogglePlayPause:
			self.play_pause()
		elif event.key() == QtCore.Qt.Key.Key_BracketLeft:
			add_speed(-5)
		elif event.key() == QtCore.Qt.Key.Key_BracketRight:
			add_speed(5)
		elif event.key() == QtCore.Qt.Key.Key_B and self.audio_tracks:
			track_id = self.player.audio_get_track()
			if event.modifiers() != QtCore.Qt.Key.Key_Shift:
				track_id, name = self.audio_tracks.next(track_id)
			else:
				track_id, name = self.audio_tracks.prev(track_id)
			if self.player.audio_set_track(track_id) == 0:
				self.show_info('Audio track: ' + name)
		elif event.key() == QtCore.Qt.Key.Key_Escape:
			self.esc_fullscreen()
		else:
			return
		event.accept()

	def set_media(self, media: vlc.Media, name: str):
		self.setWindowTitle(name)
		self.player.set_media(media)
		events = media.event_manager()
		events.event_attach(vlc.EventType.MediaDurationChanged,	self.on_duration)
		events.event_attach(vlc.EventType.MediaParsedChanged,	self.on_parsed)

		win_id = int(self.videoframe.winId())
		if platform.system() == 'Linux':		# for Linux using the X Server
			self.player.set_xwindow(win_id)
		elif platform.system() == 'Windows':	# for Windows
			self.player.set_hwnd(win_id)
			media.add_option(':avcodec-hw=dxva2')
		elif platform.system() == 'Darwin':		# for MacOS
			self.player.set_nsobject(win_id)
		self.player.play()
	def set_peer_media(self, peer: Peer, hash: int):
		self.state_timer.stop()
		self.peer = peer
		self.hash = hash
		reader = VlcReader(self.community, peer, hash)
		opaque = ctypes.cast(ctypes.pointer(ctypes.py_object(reader)), ctypes.c_void_p)
		media = self.instance.media_new_callbacks(
			reader.open, reader.read, reader.seek, reader.close, opaque)
		self.set_media(media, reader.name)

	def wait_pause(self, time_ms: int):
		self.state_timer.stop()
		self.player.pause()
		self.wait_signal.emit(time_ms)
	def send_state(self, is_playing: bool):
		self.community.send_state(PosInfo(
			self.hash,
			self.clock,
			self.player.get_time(),
			self.get_speed() if is_playing else 0,
			self.peer.mid if self.peer else bytes()))
	def update_state(self, is_playing: bool, add: int = 1):
		self.state_signal.emit()
		self.clock += add
		self.send_state(is_playing)
	def on_state(self, state: PosInfo):
		if self.clock > state.clock or self.wait_timer.isActive() or not self.loading.isHidden():
			return
		
		def update_speed(speed: int):
			if self.get_speed() != speed:
				self.set_speed(speed)

		def new_file():
			if self.clock < state.clock or self.hash < state.hash:
				new_peer = self.community.find_peer(state.peer_mid)
				if not new_peer:
					self.player.stop()
					return
				self.set_peer_media(new_peer, state.hash)
				self.player.set_time(state.time)
				if state.speed:
					update_speed(state.speed)
		def new_pos():
			dpos = self.player.get_time() - state.time
			if abs(dpos) >= Delay2 and (self.clock < state.clock or dpos > 0):
				self.player.set_time(state.time)
			if self.player.is_playing():
				if self.clock < state.clock or self.get_speed() > state.speed:
					if state.speed > 0:
						update_speed(state.speed)
					else:
						self.player.pause()
						return
				if dpos in range(Delay1, Delay2):
					self.wait_pause(dpos - WaitDelay)
			elif state.speed > 0:
				update_speed(state.speed)
				self.player.play()
			self.clock = state.clock

		peer_mid = self.peer.mid if self.peer else bytes()
		if state.peer_mid != peer_mid or state.hash != self.hash:
			new_file()
		elif self.peer:
			new_pos()

	def open_dialog(self):
		filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose Media File', '.')
		if filename:
			self.community.open_file(filename)
			self.peer = self.community.my_peer
			self.hash = self.community.file_hash
			media = self.instance.media_new(filename)
			self.set_media(media, os.path.basename(filename))

	def update_scale(self):
		if self.state_timer.isActive() and self.loading.isHidden():
			self.player.video_set_scale(max(
				float(self.width()) / self.player.video_get_width(),
				float(self.height())/ self.player.video_get_height()))
	def resizeEvent(self, event):
		if self.player.video_get_scale():
			self.update_scale()
		return super().resizeEvent(event)

	def eventFilter(self, obj, event: QtCore.QEvent):
		if event.type() == QtCore.QEvent.Type.HoverMove:
			if not self.cursor_timer.isActive():
				self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
			self.cursor_timer.start()
		return super().eventFilter(obj, event)

if __name__ == "__main__":
	key_id = sys.argv[1] if len(sys.argv) == 2 else ''
	app = QtWidgets.QApplication([])
	player = Player(f'key{key_id}.pem')
	player.show()
	player.resize(640, 480)
	if len(key_id):
		player.setWindowTitle(key_id)
	sys.exit(app.exec_())

