package com.example.photosorter.media

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.DocumentsContract
import android.system.Os
import android.system.OsConstants
import android.webkit.MimeTypeMap
import com.example.photosorter.model.AlbumMapping
import com.example.photosorter.model.PhotoItem
import com.example.photosorter.model.targetKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID
import kotlin.coroutines.resume

/** Creates a new gallery image without changing or deleting the source image. */
class PhotoCopyManager(context: Context) {
    private val appContext = context.applicationContext

    /** Verifies a selected existing album before registration, leaving no published gallery item. */
    suspend fun canWrite(mapping: AlbumMapping): Boolean = withContext(Dispatchers.IO) {
        val path = normalizeImageAlbumPath(mapping.relativePath) ?: return@withContext false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val volume = normalizedVolume(mapping.volumeName)
            if (volume !in MediaStore.getExternalVolumeNames(appContext)) return@withContext false
            val collection = MediaStore.Images.Media.getContentUri(volume)
            if (!mapping.isAppCreated && !existingAlbumStillVisible(collection, path, mapping.bucketId)) {
                return@withContext false
            }
            val resolver = appContext.contentResolver
            val probe = try {
                resolver.insert(collection, ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, "photosorter_probe_${UUID.randomUUID()}.jpg")
                    put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, path)
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }) ?: return@withContext false
            } catch (_: Exception) {
                return@withContext false
            }
            val wrote = try {
                resolver.openOutputStream(probe, "w")?.use { it.write(0) } != null
            } catch (_: Exception) {
                false
            }
            val removed = runCatching { resolver.delete(probe, null, null) == 1 }.getOrDefault(false)
            wrote && removed
        } else {
            if (mapping.volumeName != LEGACY_PRIMARY_VOLUME && mapping.volumeName != "primary") {
                return@withContext false
            }
            @Suppress("DEPRECATION")
            val root = Environment.getExternalStorageDirectory().canonicalFile
            val directory = File(root, path).canonicalFile
            if (!directory.path.startsWith(root.path + File.separator) || !directory.isDirectory) {
                return@withContext false
            }
            val probe = try {
                File.createTempFile(".photosorter_probe_", ".tmp", directory)
            } catch (_: Exception) {
                return@withContext false
            }
            val wrote = runCatching { FileOutputStream(probe).use { it.write(0) }; true }
                .getOrDefault(false)
            val removed = probe.delete()
            wrote && removed
        }
    }

    suspend fun copy(item: PhotoItem, mapping: AlbumMapping): Uri = withContext(Dispatchers.IO) {
        if (mapping.targetKey() in item.completedTargets) {
            throw IllegalStateException("이 사진은 이미 '${mapping.albumDisplayName}' 앨범에 복사되었습니다")
        }
        if (!item.mimeType.startsWith("image/") || item.mimeType == "image/*") {
            throw IOException("사진 파일만 복사할 수 있습니다")
        }
        val sourceUri = Uri.parse(item.sourceUri)
        if (sourceUri.scheme != "content") throw IOException("원본 사진을 열 수 없습니다")
        val relativePath = normalizeImageAlbumPath(mapping.relativePath)
            ?: throw IOException("이 앨범에는 저장 가능한 로컬 사진 위치가 없습니다")
        val extension = extensionForMime(item.mimeType)
        val fileName = safePhotoFileName(item.displayName, extension)
        // Photo Picker URIs do not always expose dates. When they do, carry the
        // source's gallery date to copies whose image bytes contain no EXIF date.
        val sourceDateMillis = sourceGalleryDateMillis(sourceUri)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            copyWithMediaStore(sourceUri, fileName, item.mimeType, mapping, relativePath, sourceDateMillis)
        } else {
            copyLegacy(sourceUri, fileName, item.mimeType, mapping, relativePath, sourceDateMillis)
        }
    }

    /** MediaStore dates are provider metadata, so a picker may legitimately omit them. */
    private fun sourceGalleryDateMillis(sourceUri: Uri): Long? {
        val taken = queryPositiveDate(sourceUri, MediaStore.Images.ImageColumns.DATE_TAKEN)
        if (taken != null) return taken
        val modifiedSeconds = queryPositiveDate(sourceUri, MediaStore.MediaColumns.DATE_MODIFIED)
        if (modifiedSeconds != null && modifiedSeconds <= Long.MAX_VALUE / 1000) {
            return modifiedSeconds * 1000
        }
        return queryPositiveDate(sourceUri, DocumentsContract.Document.COLUMN_LAST_MODIFIED)
            ?: sourceFileDateMillis(sourceUri)
    }

    private fun queryPositiveDate(uri: Uri, columnName: String): Long? = try {
        appContext.contentResolver.query(uri, arrayOf(columnName), null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val index = cursor.getColumnIndex(columnName)
            if (index < 0 || cursor.isNull(index)) null else cursor.getLong(index).takeIf { it > 0 }
        }
    } catch (_: Exception) {
        null
    }

    /** Some picker providers expose the actual local file only through the read descriptor. */
    private fun sourceFileDateMillis(uri: Uri): Long? = runCatching {
        appContext.contentResolver.openFileDescriptor(uri, "r")?.use { descriptor ->
            val stat = Os.fstat(descriptor.fileDescriptor)
            stat.st_mtime.takeIf {
                OsConstants.S_ISREG(stat.st_mode) && it > 0 && it <= Long.MAX_VALUE / 1000
            }?.times(1000)
        }
    }.getOrNull()

    private suspend fun copyWithMediaStore(
        sourceUri: Uri,
        fileName: String,
        mimeType: String,
        mapping: AlbumMapping,
        relativePath: String,
        sourceDateMillis: Long?,
    ): Uri {
        val volumeName = normalizedVolume(mapping.volumeName)
        if (volumeName !in MediaStore.getExternalVolumeNames(appContext)) {
            throw IOException("대상 저장소를 사용할 수 없습니다")
        }
        val resolver = appContext.contentResolver
        val collection = MediaStore.Images.Media.getContentUri(volumeName)
        if (!mapping.isAppCreated && !existingAlbumStillVisible(collection, relativePath, mapping.bucketId)) {
            throw IOException("등록한 위치에서 앨범을 찾을 수 없습니다")
        }
        val uniqueName = uniqueMediaFileName(collection, relativePath, fileName)
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, uniqueName)
            put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }

        resolver.openInputStream(sourceUri)?.use { input ->
            val destination = resolver.insert(collection, values)
                ?: throw IOException("선택한 앨범에 사진을 만들 수 없습니다")
            try {
                val output = resolver.openOutputStream(destination, "w")
                    ?: throw IOException("선택한 앨범에 사진을 쓸 수 없습니다")
                val bytesCopied = output.use { copyBytes(input, it) }
                if (bytesCopied == 0L) throw IOException("선택한 사진이 비어 있습니다")

                // File mtime is MediaStore's fallback date for images without an
                // embedded capture date. Set it while the item is still pending so
                // the provider scans the original date when publishing it.
                preserveDateOnOwnedMedia(destination, sourceDateMillis)

                val published = resolver.update(
                    destination,
                    ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                    null,
                    null,
                )
                if (published != 1) throw IOException("복사한 사진을 갤러리에 표시할 수 없습니다")
                return destination
            } catch (error: Throwable) {
                // A half-written or unpublished item should never appear as a completed copy.
                runCatching { resolver.delete(destination, null, null) }
                throw error
            }
        } ?: throw IOException("선택한 사진을 열 수 없습니다. 다시 선택해 주세요")
    }

    private fun preserveDateOnOwnedMedia(destination: Uri, sourceDateMillis: Long?) {
        if (sourceDateMillis == null) return
        runCatching {
            val path = appContext.contentResolver.query(
                destination,
                arrayOf(MediaStore.MediaColumns.DATA),
                null,
                null,
                null,
            )?.use { cursor ->
                if (!cursor.moveToFirst()) return@use null
                cursor.getColumnIndex(MediaStore.MediaColumns.DATA).takeIf { it >= 0 }
                    ?.let(cursor::getString)
            }
            if (path != null) File(path).setLastModified(sourceDateMillis)
        }
        // Direct file access can be unavailable on some providers/Android versions;
        // the copy itself must still succeed and retain its unchanged image bytes.
    }

    private fun normalizedVolume(name: String): String = when (name) {
        "primary", LEGACY_PRIMARY_VOLUME -> MediaStore.VOLUME_EXTERNAL_PRIMARY
        else -> name
    }

    private fun existingAlbumStillVisible(collection: Uri, path: String, bucketId: String?): Boolean {
        val selection = if (bucketId == null) {
            "${MediaStore.MediaColumns.RELATIVE_PATH}=?"
        } else {
            "${MediaStore.MediaColumns.RELATIVE_PATH}=? AND ${MediaStore.Images.Media.BUCKET_ID}=?"
        }
        val arguments = if (bucketId == null) arrayOf(path) else arrayOf(path, bucketId)
        return appContext.contentResolver.query(
            collection,
            arrayOf(MediaStore.MediaColumns._ID),
            selection,
            arguments,
            null,
        )?.use { it.moveToFirst() } ?: false
    }

    private fun uniqueMediaFileName(collection: Uri, relativePath: String, requestedName: String): String {
        val resolver = appContext.contentResolver
        for (suffix in 0..9999) {
            val candidate = numberedName(requestedName, suffix)
            val exists = resolver.query(
                collection,
                arrayOf(MediaStore.MediaColumns._ID),
                "${MediaStore.MediaColumns.RELATIVE_PATH}=? AND ${MediaStore.MediaColumns.DISPLAY_NAME}=?",
                arrayOf(relativePath, candidate),
                null,
            )?.use { it.moveToFirst() }
                ?: throw IOException("대상 앨범의 파일 이름을 확인할 수 없습니다")
            if (!exists) return candidate
        }
        throw IOException("같은 이름의 사진이 너무 많습니다")
    }

    private suspend fun copyLegacy(
        sourceUri: Uri,
        fileName: String,
        mimeType: String,
        mapping: AlbumMapping,
        relativePath: String,
        sourceDateMillis: Long?,
    ): Uri {
        if (mapping.volumeName != LEGACY_PRIMARY_VOLUME && mapping.volumeName != "primary") {
            throw IOException("이 Android 버전에서는 대상 저장소를 지원하지 않습니다")
        }
        @Suppress("DEPRECATION")
        val root = Environment.getExternalStorageDirectory().canonicalFile
        val directory = File(root, relativePath).canonicalFile
        if (!directory.path.startsWith(root.path + File.separator)) {
            throw IOException("선택한 앨범 위치가 올바르지 않습니다")
        }
        if (mapping.isAppCreated) {
            if (!directory.isDirectory && !directory.mkdirs()) {
                throw IOException("새 앨범을 만들 수 없습니다")
            }
        } else if (!directory.isDirectory) {
            throw IOException("선택한 앨범이 더 이상 존재하지 않습니다")
        }

        val destination = createUniqueLegacyFile(directory, fileName)
        try {
            val input = appContext.contentResolver.openInputStream(sourceUri)
                ?: throw IOException("선택한 사진을 열 수 없습니다. 다시 선택해 주세요")
            input.use { stream ->
                FileOutputStream(destination).use { output ->
                    val bytesCopied = copyBytes(stream, output)
                    if (bytesCopied == 0L) throw IOException("선택한 사진이 비어 있습니다")
                    output.fd.sync()
                }
            }
            if (sourceDateMillis != null) destination.setLastModified(sourceDateMillis)
            return withTimeout(15_000) {
                scanFile(destination, mimeType)
            } ?: throw IOException("복사한 사진을 갤러리에 등록할 수 없습니다")
        } catch (error: Throwable) {
            runCatching { destination.delete() }
            throw error
        }
    }

    private fun createUniqueLegacyFile(directory: File, requestedName: String): File {
        for (suffix in 0..9999) {
            val file = File(directory, numberedName(requestedName, suffix))
            if (file.createNewFile()) return file
        }
        throw IOException("같은 이름의 사진이 너무 많습니다")
    }

    private suspend fun scanFile(file: File, mimeType: String): Uri? =
        suspendCancellableCoroutine { continuation ->
            MediaScannerConnection.scanFile(
                appContext,
                arrayOf(file.absolutePath),
                arrayOf(mimeType),
            ) { _, uri ->
                if (continuation.isActive) continuation.resume(uri)
            }
        }

    private suspend fun copyBytes(input: InputStream, output: OutputStream): Long {
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        var total = 0L
        while (true) {
            currentCoroutineContext().ensureActive()
            val size = input.read(buffer)
            if (size < 0) break
            output.write(buffer, 0, size)
            total += size
        }
        output.flush()
        return total
    }

    private fun numberedName(name: String, suffix: Int): String {
        if (suffix == 0) return name
        val dot = name.lastIndexOf('.')
        return if (dot > 0) {
            "${name.substring(0, dot)}_$suffix${name.substring(dot)}"
        } else {
            "${name}_$suffix"
        }
    }

    private fun extensionForMime(mimeType: String): String = when (mimeType.lowercase()) {
        "image/jpeg", "image/jpg" -> "jpg"
        "image/png" -> "png"
        "image/webp" -> "webp"
        "image/heic" -> "heic"
        "image/heif" -> "heif"
        "image/gif" -> "gif"
        "image/bmp" -> "bmp"
        "image/avif" -> "avif"
        else -> MimeTypeMap.getSingleton().getExtensionFromMimeType(mimeType) ?: "img"
    }
}
