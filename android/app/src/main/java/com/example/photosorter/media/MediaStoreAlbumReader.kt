package com.example.photosorter.media

import android.content.ContentUris
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import com.example.photosorter.model.DeviceAlbum
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.nio.charset.StandardCharsets
import java.util.UUID

/** Reads local image buckets. A bucket ID alone does not prove that an album can be written to. */
class MediaStoreAlbumReader(context: Context) {
    private val appContext = context.applicationContext

    suspend fun listAlbums(): List<DeviceAlbum> = withContext(Dispatchers.IO) {
        val modern = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        val queryUri = if (modern) {
            MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
        } else {
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        }
        val columns = mutableListOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.BUCKET_ID,
            MediaStore.Images.Media.BUCKET_DISPLAY_NAME,
            MediaStore.Images.Media.DATE_ADDED,
        )
        if (modern) {
            columns += MediaStore.MediaColumns.RELATIVE_PATH
            columns += MediaStore.MediaColumns.VOLUME_NAME
        } else {
            @Suppress("DEPRECATION")
            columns.add(MediaStore.MediaColumns.DATA)
        }

        val mountedVolumes = if (modern) MediaStore.getExternalVolumeNames(appContext) else emptySet()
        val albums = LinkedHashMap<String, AlbumBuilder>()
        val cursor = appContext.contentResolver.query(
            queryUri,
            columns.toTypedArray(),
            null,
            null,
            "${MediaStore.Images.Media.DATE_ADDED} DESC, ${MediaStore.Images.Media._ID} DESC",
        ) ?: throw IOException("앨범 목록을 읽을 수 없습니다")
        cursor.use {
            val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
            val bucketColumn = cursor.getColumnIndexOrThrow(MediaStore.Images.Media.BUCKET_ID)
            val titleColumn = cursor.getColumnIndexOrThrow(MediaStore.Images.Media.BUCKET_DISPLAY_NAME)
            val pathColumn = cursor.getColumnIndexOrThrow(
                if (modern) MediaStore.MediaColumns.RELATIVE_PATH else MediaStore.MediaColumns.DATA
            )
            val volumeColumn = if (modern) {
                cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.VOLUME_NAME)
            } else -1

            while (cursor.moveToNext()) {
                val imageId = cursor.getLong(idColumn)
                val bucketId = cursor.getString(bucketColumn)
                val rawPath = cursor.getString(pathColumn)
                val relativePath = if (modern) {
                    normalizeImageAlbumPath(rawPath)
                } else {
                    legacyImageAlbumPath(rawPath)
                }
                val volumeName = if (modern) {
                    cursor.getString(volumeColumn)?.takeIf { it.isNotBlank() } ?: "unknown"
                } else {
                    LEGACY_PRIMARY_VOLUME
                }
                val rawName = cursor.getString(titleColumn)?.trim().orEmpty()
                val displayName = rawName.ifBlank {
                    relativePath?.trimEnd('/')?.substringAfterLast('/') ?: "이름 없는 앨범"
                }
                val albumId = UUID.nameUUIDFromBytes(
                    "$volumeName\u0000${bucketId.orEmpty()}\u0000${relativePath ?: rawPath.orEmpty()}"
                        .toByteArray(StandardCharsets.UTF_8)
                ).toString()
                val itemUri = ContentUris.withAppendedId(
                    if (modern && volumeName != "unknown") {
                        MediaStore.Images.Media.getContentUri(volumeName)
                    } else queryUri,
                    imageId,
                ).toString()
                val album = albums[albumId]
                if (album == null) {
                    albums[albumId] = AlbumBuilder(
                        id = albumId,
                        displayName = displayName,
                        count = 1,
                        coverUri = itemUri,
                        bucketId = bucketId,
                        volumeName = volumeName,
                        relativePath = relativePath,
                        writable = relativePath != null && (!modern || volumeName in mountedVolumes),
                    )
                } else {
                    album.count++
                }
            }
        }
        albums.values.map { it.toDeviceAlbum() }
    }

    private data class AlbumBuilder(
        val id: String,
        val displayName: String,
        var count: Int,
        val coverUri: String,
        val bucketId: String?,
        val volumeName: String,
        val relativePath: String?,
        val writable: Boolean,
    ) {
        fun toDeviceAlbum() = DeviceAlbum(
            id = id,
            displayName = displayName,
            count = count,
            coverUri = coverUri,
            bucketId = bucketId,
            volumeName = volumeName,
            relativePath = relativePath,
            writable = writable,
        )
    }
}

internal const val LEGACY_PRIMARY_VOLUME = "external"

/** Restrict destinations to standard shared image areas; never trust a path from a media row. */
internal fun normalizeImageAlbumPath(path: String?): String? {
    if (path.isNullOrBlank() || path.startsWith('/') || '\\' in path) return null
    val parts = path.split('/').filter { it.isNotEmpty() }
    if (parts.isEmpty() || parts.any { segment ->
            segment == "." || segment == ".." || segment.any { char -> char.code < 32 || char.code == 127 }
        }) {
        return null
    }
    // These are the stable on-disk names of Environment.DIRECTORY_PICTURES/DCIM.
    // Keeping validation pure also lets it run in local JVM tests.
    if (parts.first() != "Pictures" &&
        parts.first() != "DCIM"
    ) return null
    return parts.joinToString("/") + "/"
}

private fun legacyImageAlbumPath(dataPath: String?): String? {
    if (dataPath.isNullOrBlank()) return null
    @Suppress("DEPRECATION")
    val root = Environment.getExternalStorageDirectory().canonicalFile
    val parent = File(dataPath).parentFile?.canonicalFile ?: return null
    val prefix = root.path + File.separator
    if (!parent.path.startsWith(prefix)) return null
    return normalizeImageAlbumPath(parent.path.removePrefix(prefix).replace(File.separatorChar, '/') + "/")
}
