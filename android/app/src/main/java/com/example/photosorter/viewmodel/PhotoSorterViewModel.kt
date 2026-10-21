package com.example.photosorter.viewmodel

import android.app.Application
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.MediaStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.photosorter.data.StateStore
import com.example.photosorter.media.MediaStoreAlbumReader
import com.example.photosorter.media.LocalGalleryAlbum
import com.example.photosorter.media.LocalGalleryPhoto
import com.example.photosorter.media.LocalGalleryReader
import com.example.photosorter.media.PhotoCopyManager
import com.example.photosorter.media.PhotoMetadataReader
import com.example.photosorter.model.AlbumMapping
import com.example.photosorter.model.DeviceAlbum
import com.example.photosorter.model.PhotoItem
import com.example.photosorter.model.PhotoStatus
import com.example.photosorter.model.SorterData
import com.example.photosorter.model.targetKey
import java.util.UUID
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

data class SorterUiState(
    val mappings: List<AlbumMapping> = emptyList(),
    val albums: List<DeviceAlbum> = emptyList(),
    val items: List<PhotoItem> = emptyList(),
    val currentIndex: Int = 0,
    val busy: Boolean = false,
    val loadingAlbums: Boolean = false,
    val error: String? = null,
    val gallery: LocalGalleryUiState = LocalGalleryUiState(),
)

data class LocalGalleryUiState(
    val albums: List<LocalGalleryAlbum> = emptyList(),
    val photos: List<LocalGalleryPhoto> = emptyList(),
    val currentAlbumKey: String? = null,
    val selectedUris: Set<String> = emptySet(),
    val showProcessed: Boolean = false,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val hasMore: Boolean = false,
    val error: String? = null,
)

class PhotoSorterViewModel(application: Application) : AndroidViewModel(application) {
    private val appContext = application.applicationContext
    private val store = StateStore(appContext)
    private val albumReader = MediaStoreAlbumReader(appContext)
    private val galleryReader = LocalGalleryReader(appContext)
    private val metadataReader = PhotoMetadataReader(appContext)
    private val copyManager = PhotoCopyManager(appContext)
    private val mutation = Mutex()
    private val submitting = AtomicBoolean(false)
    private var lastSubmitAt = 0L
    private var saved = SorterData()
    private var storageHealthy = true
    private var galleryGeneration = 0

    private val _state = MutableStateFlow(SorterUiState())
    val state: StateFlow<SorterUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            mutation.withLock {
                try {
                    saved = store.load()
                    publish()
                } catch (error: Exception) {
                    storageHealthy = false
                    showError("저장된 작업을 읽지 못해 변경을 중지했습니다. 앱 데이터를 보존한 채 복구가 필요합니다: ${error.message.orEmpty()}")
                }
            }
        }
    }

    fun refreshAlbums() {
        viewModelScope.launch {
            _state.update { it.copy(loadingAlbums = true, error = null) }
            try {
                val albums = withContext(Dispatchers.IO) { albumReader.listAlbums() }
                _state.update { it.copy(albums = albums, loadingAlbums = false) }
            } catch (_: SecurityException) {
                _state.update {
                    it.copy(albums = emptyList(), loadingAlbums = false,
                        error = "사진 접근 권한이 없습니다. 권한을 확인한 뒤 다시 시도해 주세요.")
                }
            } catch (error: Exception) {
                _state.update {
                    it.copy(albums = emptyList(), loadingAlbums = false,
                        error = "앨범을 불러오지 못했습니다: ${error.message.orEmpty()}")
                }
            }
        }
    }

    /** Read the same on-device image collection that gallery apps index. */
    fun refreshLocalGallery() {
        val generation = ++galleryGeneration
        val previous = _state.value.gallery
        val hiddenUris = processedGalleryUris()
        _state.update {
            it.copy(gallery = it.gallery.copy(
                photos = emptyList(), loading = true, loadingMore = false,
                hasMore = false, error = null,
            ))
        }
        viewModelScope.launch {
            try {
                val albums = galleryReader.listAlbums(previous.showProcessed, hiddenUris)
                val readableSelection = withContext(Dispatchers.IO) {
                    previous.selectedUris.filterTo(mutableSetOf()) { uri ->
                        runCatching {
                            appContext.contentResolver.openFileDescriptor(Uri.parse(uri), "r")
                                ?.use { true } ?: false
                        }.getOrDefault(false)
                    }
                }
                val albumKey = previous.currentAlbumKey?.takeIf { key ->
                    albums.any { it.key == key }
                }
                val page = albumKey?.let {
                    galleryReader.listPhotos(it, 0, GALLERY_PAGE_SIZE,
                        previous.showProcessed, hiddenUris)
                }
                if (generation != galleryGeneration) return@launch
                _state.update { state ->
                    state.copy(gallery = state.gallery.copy(
                        albums = albums,
                        currentAlbumKey = albumKey,
                        photos = page?.photos.orEmpty(),
                        hasMore = page?.hasMore ?: false,
                        selectedUris = readableSelection,
                        loading = false,
                    ))
                }
            } catch (error: Exception) {
                if (generation != galleryGeneration) return@launch
                _state.update { state ->
                    state.copy(gallery = state.gallery.copy(
                        albums = emptyList(), photos = emptyList(), loading = false,
                        hasMore = false,
                        error = "휴대전화 사진을 불러오지 못했습니다. 사진 접근 권한을 확인해 주세요: ${error.message.orEmpty()}",
                    ))
                }
            }
        }
    }

    fun openLocalGalleryAlbum(albumKey: String) {
        if (_state.value.gallery.albums.none { it.key == albumKey }) return
        val generation = ++galleryGeneration
        val showProcessed = _state.value.gallery.showProcessed
        val hiddenUris = processedGalleryUris()
        _state.update { state ->
            state.copy(gallery = state.gallery.copy(
                currentAlbumKey = albumKey, photos = emptyList(), loading = true,
                loadingMore = false, hasMore = false, error = null,
            ))
        }
        viewModelScope.launch {
            try {
                val page = galleryReader.listPhotos(albumKey, 0, GALLERY_PAGE_SIZE,
                    showProcessed, hiddenUris)
                if (generation != galleryGeneration) return@launch
                _state.update { state ->
                    state.copy(gallery = state.gallery.copy(
                        photos = page.photos, hasMore = page.hasMore, loading = false,
                    ))
                }
            } catch (error: Exception) {
                if (generation != galleryGeneration) return@launch
                _state.update { state ->
                    state.copy(gallery = state.gallery.copy(
                        photos = emptyList(), loading = false,
                        error = "앨범 사진을 불러오지 못했습니다: ${error.message.orEmpty()}",
                    ))
                }
            }
        }
    }

    fun backToLocalGalleryAlbums() {
        galleryGeneration++
        _state.update { state ->
            state.copy(gallery = state.gallery.copy(
                currentAlbumKey = null, photos = emptyList(), loading = false,
                loadingMore = false, hasMore = false, error = null,
            ))
        }
    }

    fun toggleLocalGalleryPhoto(uri: String) {
        if (_state.value.gallery.photos.none { it.uri == uri }) return
        _state.update { state ->
            val selected = state.gallery.selectedUris
            state.copy(gallery = state.gallery.copy(
                selectedUris = if (uri in selected) selected - uri else selected + uri,
            ))
        }
    }

    fun toggleLocalGalleryProcessed() {
        _state.update { state ->
            state.copy(gallery = state.gallery.copy(
                showProcessed = !state.gallery.showProcessed,
                selectedUris = emptySet(),
            ))
        }
        refreshLocalGallery()
    }

    fun loadMoreLocalGalleryPhotos() {
        val current = _state.value.gallery
        val key = current.currentAlbumKey ?: return
        if (current.loading || current.loadingMore || !current.hasMore) return
        val generation = galleryGeneration
        val hiddenUris = processedGalleryUris()
        _state.update { state ->
            state.copy(gallery = state.gallery.copy(loadingMore = true, error = null))
        }
        viewModelScope.launch {
            try {
                val page = galleryReader.listPhotos(key, current.photos.size, GALLERY_PAGE_SIZE,
                    current.showProcessed, hiddenUris)
                if (generation != galleryGeneration) return@launch
                _state.update { state ->
                    state.copy(gallery = state.gallery.copy(
                        photos = state.gallery.photos + page.photos,
                        hasMore = page.hasMore,
                        loadingMore = false,
                    ))
                }
            } catch (error: Exception) {
                if (generation != galleryGeneration) return@launch
                _state.update { state ->
                    state.copy(gallery = state.gallery.copy(
                        loadingMore = false,
                        error = "사진을 더 불러오지 못했습니다: ${error.message.orEmpty()}",
                    ))
                }
            }
        }
    }

    fun clearLocalGallery() {
        galleryGeneration++
        _state.update { it.copy(gallery = LocalGalleryUiState()) }
    }

    private fun processedGalleryUris(): Set<String> =
        saved.copyLedger.filterValues { it.isNotEmpty() }.keys + saved.createdCopyUris

    fun addAlbum(album: DeviceAlbum) {
        viewModelScope.launch {
            try {
                mutation.withLock {
                if (!storageReady()) return@withLock
                val path = album.relativePath
                if (!album.writable || path.isNullOrBlank()) {
                    showError("이 앨범은 사진을 저장할 수 없습니다. 새 앨범을 만들어 주세요.")
                    return@withLock
                }
                if (saved.mappings.any { it.id == album.id }) {
                    showError("이미 등록된 앨범입니다.")
                    return@withLock
                }
                if (saved.mappings.any {
                        it.targetKey() == targetKey(album.volumeName, path)
                    }
                ) {
                    showError("같은 저장 위치의 앨범이 이미 등록되어 있습니다.")
                    return@withLock
                }
                val alias = uniqueAlias(album.displayName)
                val mapping = AlbumMapping(
                    id = album.id,
                    inputName = alias,
                    albumDisplayName = album.displayName,
                    bucketId = album.bucketId,
                    volumeName = album.volumeName,
                    relativePath = path,
                    isAppCreated = false,
                )
                val writable = try {
                    withContext(Dispatchers.IO) { copyManager.canWrite(mapping) }
                } catch (_: Exception) {
                    false
                }
                if (!writable) {
                    showError("이 앨범에 저장할 수 없습니다. 새 앨범을 만들어 주세요.")
                    return@withLock
                }
                commit(saved.copy(mappings = saved.mappings + mapping))
                }
            } catch (error: Exception) {
                showError("앨범 등록을 저장하지 못했습니다: ${error.message.orEmpty()}")
            }
        }
    }

    fun createAlbum(name: String) {
        viewModelScope.launch {
            try {
                mutation.withLock {
                if (!storageReady()) return@withLock
                val clean = name.trim()
                if (clean.isEmpty() || clean == "." || clean == ".." ||
                    clean.any { it == '/' || it == '\\' || it.code < 32 } || clean.length > 80
                ) {
                    showError("앨범 이름을 확인해 주세요. 슬래시와 특수 제어 문자는 사용할 수 없습니다.")
                    return@withLock
                }
                val relativePath = "Pictures/$clean/"
                val primaryVolume = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    MediaStore.VOLUME_EXTERNAL_PRIMARY
                } else {
                    "external"
                }
                if (saved.mappings.any {
                        it.targetKey() == targetKey(primaryVolume, relativePath)
                    }
                ) {
                    showError("같은 이름의 앨범이 이미 등록되어 있습니다.")
                    return@withLock
                }
                if (_state.value.albums.any {
                        it.volumeName == primaryVolume &&
                            it.relativePath.equals(relativePath, ignoreCase = true)
                    }
                ) {
                    showError("기기에 이미 있는 앨범입니다. 앨범 선택에서 등록해 주세요.")
                    return@withLock
                }
                val alias = uniqueAlias(clean)
                commit(saved.copy(mappings = saved.mappings + AlbumMapping(
                    id = UUID.randomUUID().toString(),
                    inputName = alias,
                    albumDisplayName = clean,
                    bucketId = null,
                    volumeName = primaryVolume,
                    relativePath = relativePath,
                    isAppCreated = true,
                )))
                }
            } catch (error: Exception) {
                showError("새 앨범 등록을 저장하지 못했습니다: ${error.message.orEmpty()}")
            }
        }
    }

    fun updateAlias(id: String, alias: String) {
        viewModelScope.launch {
            try {
                mutation.withLock {
                if (!storageReady()) return@withLock
                val clean = alias.trim()
                if (clean.isEmpty() || clean.contains(Regex("[,\\s]"))) {
                    showError("입력 이름은 공백이나 쉼표 없이 입력해 주세요.")
                    return@withLock
                }
                if (saved.mappings.any { it.id != id && it.inputName == clean }) {
                    showError("이미 사용 중인 입력 이름입니다.")
                    return@withLock
                }
                val oldName = saved.mappings.firstOrNull { it.id == id }?.inputName
                if (oldName == null) {
                    showError("등록된 앨범을 찾지 못했습니다.")
                    return@withLock
                }
                commit(saved.copy(
                    mappings = saved.mappings.map {
                        if (it.id == id) it.copy(inputName = clean) else it
                    },
                    items = saved.items.map { item ->
                        item.copy(inputNames = item.inputNames.map { name ->
                            if (name == oldName) clean else name
                        })
                    },
                ))
                }
            } catch (error: Exception) {
                showError("입력 이름 변경을 저장하지 못했습니다: ${error.message.orEmpty()}")
            }
        }
    }

    fun removeAlbum(id: String) {
        viewModelScope.launch {
            try {
                mutation.withLock {
                if (!storageReady()) return@withLock
                commit(saved.copy(mappings = saved.mappings.filterNot { it.id == id }))
                }
            } catch (error: Exception) {
                showError("앨범 등록 제거를 저장하지 못했습니다: ${error.message.orEmpty()}")
            }
        }
    }

    fun selectPhotos(uris: List<Uri>) {
        if (uris.isEmpty()) return
        // The gallery action navigates immediately. Hide the previous session before the
        // coroutine starts so it cannot be displayed or submitted as the new selection.
        _state.update { it.copy(items = emptyList(), currentIndex = 0, busy = true, error = null) }
        viewModelScope.launch {
            mutation.withLock {
                if (!storageReady()) {
                    _state.update { it.copy(busy = false) }
                    return@withLock
                }
                val previousSession = saved
                try {
                    val items = withContext(Dispatchers.IO) {
                        uris.distinct().map { uri ->
                            metadataReader.read(uri).copy(
                                completedTargets = saved.copyLedger[uri.toString()].orEmpty()
                            )
                        }
                    }
                    saved = saved.copy(items = items, currentIndex = 0)
                    persist()
                    _state.update { it.copy(gallery = it.gallery.copy(selectedUris = emptySet())) }
                } catch (error: Exception) {
                    saved = previousSession
                    publish()
                    showError("선택한 사진을 읽지 못했습니다. 다시 선택해 주세요: ${error.message.orEmpty()}")
                } finally {
                    _state.update { it.copy(busy = false) }
                }
            }
        }
    }

    fun submit(selectedTargets: Set<String>) {
        // A repeated tap cannot advance two photos while one action is running.
        if (_state.value.busy) return
        if (!submitting.compareAndSet(false, true)) return
        val now = SystemClock.elapsedRealtime()
        if (now - lastSubmitAt < 180L) {
            submitting.set(false)
            return
        }
        lastSubmitAt = now
        viewModelScope.launch {
            try {
                mutation.withLock { submitLocked(selectedTargets) }
            } catch (error: Exception) {
                showError("진행 기록을 저장하지 못했습니다. 저장 공간을 확인하고 다시 시도해 주세요: ${error.message.orEmpty()}")
            } finally {
                _state.update { it.copy(busy = false) }
                submitting.set(false)
            }
        }
    }

    private suspend fun submitLocked(selectedTargets: Set<String>) {
        if (!storageReady()) return
        val index = saved.currentIndex
        val current = saved.items.getOrNull(index) ?: return
        if (selectedTargets.isEmpty()) {
            _state.update { it.copy(busy = true, error = null) }
            val readable = withContext(Dispatchers.IO) {
                try {
                    appContext.contentResolver.openInputStream(Uri.parse(current.sourceUri))
                        ?.use { true } ?: false
                } catch (_: Exception) {
                    false
                }
            }
            if (!readable) {
                showError("원본 사진에 접근할 수 없습니다. 사진을 다시 선택해 주세요.")
                return
            }
            val alreadyCopied = current.completedTargets.isNotEmpty()
            val nextItem = current.copy(
                status = if (alreadyCopied) PhotoStatus.COMPLETED else PhotoStatus.SKIPPED,
                inputNames = emptyList(),
                selectedTargets = emptySet(),
                errorMessage = null,
            )
            commit(saved.copy(
                items = saved.items.toMutableList().also { it[index] = nextItem },
                currentIndex = index + 1,
            ))
            return
        }
        val mappingsByTarget = saved.mappings.associateBy { it.targetKey() }
        val missing = selectedTargets.filterNot { it in mappingsByTarget }
        if (missing.isNotEmpty()) {
            showError("선택한 앨범 중 등록이 해제된 항목이 있습니다. 이전 화면에서 앨범을 다시 등록해 주세요.")
            return
        }
        val selectedMappings = saved.mappings.filter { it.targetKey() in selectedTargets }
        _state.update { it.copy(busy = true, error = null) }
        var item = current.copy(
            status = PhotoStatus.PENDING,
            inputNames = selectedMappings.map { it.inputName },
            selectedTargets = selectedTargets,
            errorMessage = null,
        )
        replaceItem(index, item)
        persist()
        for (mapping in selectedMappings) {
            val target = mapping.targetKey()
            if (target in item.completedTargets) continue
            try {
                val destination = withContext(Dispatchers.IO) { copyManager.copy(item, mapping) }
                item = item.copy(
                    completedTargets = item.completedTargets + target,
                    newCopies = item.newCopies + target,
                )
                saved = saved.copy(
                    copyLedger = saved.copyLedger +
                        (item.sourceUri to (saved.copyLedger[item.sourceUri].orEmpty() + target)),
                    createdCopyUris = saved.createdCopyUris + destination.toString(),
                )
                replaceItem(index, item)
                persist() // Preserve each successful target before attempting the next.
            } catch (error: Exception) {
                item = item.copy(status = PhotoStatus.ERROR,
                    errorMessage = "'${mapping.albumDisplayName}' 앨범에 복사하지 못했습니다: ${error.message.orEmpty()}")
                replaceItem(index, item)
                persist()
                showError(item.errorMessage.orEmpty())
                return
            }
        }
        val completedItem = item.copy(status = PhotoStatus.COMPLETED, errorMessage = null)
        commit(saved.copy(
            items = saved.items.toMutableList().also { it[index] = completedItem },
            currentIndex = index + 1,
        ))
    }

    fun previous() {
        viewModelScope.launch {
            try {
                mutation.withLock {
                if (!storageReady()) return@withLock
                if (submitting.get() || saved.currentIndex == 0) return@withLock
                commit(saved.copy(currentIndex = saved.currentIndex - 1))
                }
            } catch (error: Exception) {
                showError("이전 사진 위치를 저장하지 못했습니다: ${error.message.orEmpty()}")
            }
        }
    }

    fun resetSession() {
        viewModelScope.launch {
            try {
                mutation.withLock {
                if (!storageReady()) return@withLock
                if (submitting.get()) return@withLock
                commit(saved.copy(items = emptyList(), currentIndex = 0))
                }
            } catch (error: Exception) {
                showError("작업 초기화를 저장하지 못했습니다: ${error.message.orEmpty()}")
            }
        }
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }

    private fun storageReady(): Boolean {
        if (storageHealthy) return true
        showError("저장된 분류 기록을 읽지 못해 변경이 중지되었습니다. 앱 데이터를 보존한 채 복구가 필요합니다.")
        return false
    }

    private fun replaceItem(index: Int, item: PhotoItem) {
        saved = saved.copy(items = saved.items.toMutableList().also { it[index] = item })
    }

    private suspend fun persist() {
        if (!storageHealthy) throw IOException("이전에 저장한 기록을 읽을 수 없어 덮어쓰기를 막았습니다")
        try {
            store.save(saved)
        } catch (error: Exception) {
            throw IOException("진행 기록을 저장하지 못했습니다. 앱을 종료하지 말고 저장 공간을 확인해 주세요", error)
        }
        publish()
    }

    /** Pure state edits become visible only after DataStore accepts them. */
    private suspend fun commit(updated: SorterData) {
        val previous = saved
        saved = updated
        try {
            persist()
        } catch (error: Exception) {
            saved = previous
            throw error
        }
    }

    private fun publish() {
        _state.update { current ->
            current.copy(mappings = saved.mappings, items = saved.items,
                currentIndex = saved.currentIndex, error = null)
        }
    }

    private fun showError(message: String) {
        _state.update { it.copy(error = message) }
    }

    private fun suggestedAlias(albumName: String): String = albumName.trim()
        .replace(Regex("\\s+\\d{1,2}월$"), "")
        .replace(Regex("[,\\s]+"), "_")

    /** Keep the legacy alias field unique without making it a user-facing requirement. */
    private fun uniqueAlias(albumName: String): String {
        val base = suggestedAlias(albumName).ifBlank { "앨범" }
        val used = saved.mappings.map { it.inputName }.toSet()
        if (base !in used) return base
        var suffix = 2
        while ("${base}_$suffix" in used) suffix++
        return "${base}_$suffix"
    }

    companion object {
        private const val GALLERY_PAGE_SIZE = 120

        fun parseNames(input: String): List<String> = input.trim()
            .split(Regex("[,\\s]+"))
            .filter(String::isNotEmpty)
            .distinct()
    }
}
