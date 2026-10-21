package com.example.photosorter.media

import android.content.ContentUris
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Process
import android.provider.DocumentsContract
import android.provider.MediaStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.nio.charset.StandardCharsets
import java.util.UUID

data class LocalGalleryAlbum(
    val key: String,
    val displayName: String,
    val count: Int,
    val coverUri: String,
)

data class LocalGalleryPhoto(
    val uri: String,
    val displayName: String,
    val albumKey: String,
    val isProcessed: Boolean,
)

data class LocalGalleryPage(
    val photos: List<LocalGalleryPhoto>,
    val hasMore: Boolean,
)

/** The device's indexed image files, without cloud Photo Picker results. */
class LocalGalleryReader(context: Context) {
    private val appContext = context.applicationContext
    private val pickerCacheLock = Any()
    private val pickerUriCache = HashMap<String, String?>()
    private var pickerCacheGeneration = 0

    suspend fun listAlbums(
        showProcessed: Boolean,
        hiddenUris: Set<String>,
    ): List<LocalGalleryAlbum> = withContext(Dispatchers.IO) {
        // A gallery refresh follows activity resume, including selected-photo
        // permission changes that leave the Android permission flag unchanged.
        // Revalidate old picker grants once here; photo pages reuse the result.
        synchronized(pickerCacheLock) {
            pickerUriCache.clear()
            pickerCacheGeneration++
        }
        val effectiveHiddenUris = hiddenUris + resolvePreviouslyPickedLocalImages(hiddenUris)
        val albums = LinkedHashMap<String, AlbumCount>()
        try {
            queryImages(sorted = false).use { cursor ->
                val columns = ImageColumns(cursor)
                var scanned = 0
                while (cursor.moveToNext()) {
                    if (++scanned % 64 == 0) currentCoroutineContext().ensureActive()
                    val row = columns.read(cursor) ?: continue
                    if (!showProcessed && row.isProcessed(effectiveHiddenUris)) continue
                    val album = albums[row.albumKey]
                    if (album == null) {
                        albums[row.albumKey] = AlbumCount(
                            key = row.albumKey,
                            displayName = row.albumName,
                            count = 1,
                            coverUri = row.uri,
                            coverDate = row.sortDate,
                            coverId = row.id,
                        )
                    } else {
                        album.count++
                        if (row.sortDate > album.coverDate ||
                            (row.sortDate == album.coverDate && row.id > album.coverId)
                        ) {
                            album.coverUri = row.uri
                            album.coverDate = row.sortDate
                            album.coverId = row.id
                        }
                    }
                }
            }
        } catch (cause: SecurityException) {
            throw IOException("기기 사진 접근 권한을 확인해 주세요", cause)
        }
        albums.values.sortedWith(
            compareByDescending<AlbumCount> { it.coverDate }
                .thenByDescending { it.coverId }
                .thenBy { it.displayName }
                .thenBy { it.key }
        ).map { LocalGalleryAlbum(it.key, it.displayName, it.count, it.coverUri) }
    }

    suspend fun listPhotos(
        albumKey: String,
        offset: Int,
        limit: Int,
        showProcessed: Boolean,
        hiddenUris: Set<String>,
    ): LocalGalleryPage = withContext(Dispatchers.IO) {
        if (limit <= 0) return@withContext LocalGalleryPage(emptyList(), false)
        val effectiveHiddenUris = hiddenUris + resolvePreviouslyPickedLocalImages(hiddenUris)
        val photos = ArrayList<LocalGalleryPhoto>(limit.coerceAtMost(100))
        val skip = offset.coerceAtLeast(0)
        var eligible = 0
        var scanned = 0
        try {
            queryImages(sorted = true).use { cursor ->
                val columns = ImageColumns(cursor)
                while (cursor.moveToNext()) {
                    if (++scanned % 64 == 0) currentCoroutineContext().ensureActive()
                    val row = columns.read(cursor) ?: continue
                    val processed = row.isProcessed(effectiveHiddenUris)
                    if ((!showProcessed && processed) ||
                        (albumKey != ALL_ALBUM_KEY && row.albumKey != albumKey)
                    ) continue
                    if (eligible++ < skip) continue
                    if (photos.size == limit) {
                        return@withContext LocalGalleryPage(photos, true)
                    }
                    photos.add(
                        LocalGalleryPhoto(
                            uri = row.uri,
                            displayName = row.displayName,
                            albumKey = row.albumKey,
                            isProcessed = processed,
                        )
                    )
                }
            }
        } catch (cause: SecurityException) {
            throw IOException("기기 사진 접근 권한을 확인해 주세요", cause)
        }
        LocalGalleryPage(photos, false)
    }

    /**
     * Earlier releases stored Photo Picker URIs in their copy ledger. Picker URIs
     * are not MediaStore image URIs, even when they refer to the same local file.
     * Only the Android local provider's exact URI form is eligible here. A cloud
     * authority, missing grant, ambiguous ID, or metadata mismatch stays visible.
     */
    private fun resolvePreviouslyPickedLocalImages(hiddenUris: Set<String>): Set<String> {
        if (hiddenUris.isEmpty() || Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return emptySet()
        }
        val resolved = HashSet<String>()
        for (rawUri in hiddenUris) {
            if (!rawUri.startsWith("content://media/picker/") &&
                !rawUri.startsWith("content://media/picker_get_content/") &&
                !rawUri.startsWith("content://media/external/images/media/") &&
                !rawUri.startsWith("content://com.android.providers.media.documents/") &&
                !rawUri.startsWith("content://com.android.externalstorage.documents/")
            ) continue
            val cached = synchronized(pickerCacheLock) {
                if (pickerUriCache.containsKey(rawUri)) {
                    CacheLookup(true, pickerUriCache[rawUri], pickerCacheGeneration)
                } else {
                    CacheLookup(false, null, pickerCacheGeneration)
                }
            }
            if (cached.found) {
                cached.uri?.let(resolved::add)
                continue
            }
            val pickerUri = runCatching { Uri.parse(rawUri) }.getOrNull() ?: continue
            if (pickerUri.scheme != "content") continue
            var localUri: String? = null
            if (pickerUri.authority == MediaStore.AUTHORITY &&
                pickerUri.pathSegments.firstOrNull() == MediaStore.VOLUME_EXTERNAL
            ) {
                localUri = try {
                    canonicalMediaStoreUri(pickerUri)
                } catch (_: Exception) {
                    null
                }
            } else if (pickerUri.authority == "com.android.providers.media.documents" ||
                pickerUri.authority == "com.android.externalstorage.documents"
            ) {
                // The platform exposes an official, permission-preserving SAF
                // conversion for these two document providers on Android 10+.
                try {
                    if (DocumentsContract.isDocumentUri(appContext, pickerUri)) {
                        MediaStore.getMediaUri(appContext, pickerUri)?.let { mediaUri ->
                            localUri = canonicalMediaStoreUri(mediaUri)
                        }
                    }
                } catch (_: Exception) {
                    // The old grant may have expired; leave this photo visible.
                }
            } else {
                val imageId = localPickerImageId(
                    rawUri, Process.myUid() / ANDROID_UIDS_PER_USER
                )
                if (imageId != null) {
                    val pickerMetadata = try {
                        queryImageFingerprint(pickerUri)
                    } catch (_: Exception) {
                        null
                    }
                    if (pickerMetadata != null) {
                        localUri = try {
                            matchingMediaStoreUri(imageId, pickerMetadata)
                        } catch (_: Exception) {
                            null
                        }
                    }
                }
            }
            synchronized(pickerCacheLock) {
                if (cached.generation == pickerCacheGeneration) {
                    pickerUriCache[rawUri] = localUri
                }
            }
            if (localUri != null) resolved.add(localUri)
        }
        return resolved
    }

    private data class CacheLookup(
        val found: Boolean,
        val uri: String?,
        val generation: Int,
    )

    private fun canonicalMediaStoreUri(uri: Uri): String? {
        if (uri.scheme != "content" || uri.authority != MediaStore.AUTHORITY) return null
        val parts = uri.pathSegments
        if (parts.size != 4 || parts[1] != "images" || parts[2] != "media") return null
        val imageId = parts[3].toLongOrNull()?.takeIf { it > 0 } ?: return null
        return appContext.contentResolver.query(
            uri,
            arrayOf(MediaStore.Images.Media._ID, MediaStore.MediaColumns.VOLUME_NAME),
            null,
            null,
            null,
        )?.use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val id = cursor.longOrNull(cursor.getColumnIndex(MediaStore.Images.Media._ID))
            val volume = cursor.stringOrNull(cursor.getColumnIndex(MediaStore.MediaColumns.VOLUME_NAME))
                ?.takeIf { it.isNotBlank() }
            if (cursor.moveToNext() || id != imageId || volume == null) return@use null
            ContentUris.withAppendedId(
                MediaStore.Images.Media.getContentUri(volume), imageId
            ).toString()
        }
    }

    private fun queryImageFingerprint(uri: Uri): ImageFingerprint? {
        val columns = arrayOf(
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.WIDTH,
            MediaStore.MediaColumns.HEIGHT,
            MediaStore.Images.Media.DATE_TAKEN,
        )
        return appContext.contentResolver.query(uri, columns, null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val fingerprint = ImageFingerprint.from(cursor) ?: return@use null
            if (cursor.moveToNext()) null else fingerprint
        }
    }

    private fun matchingMediaStoreUri(
        imageId: Long,
        source: ImageFingerprint,
    ): String? {
        val collection = MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
        val columns = arrayOf(
            MediaStore.Images.Media._ID,
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.WIDTH,
            MediaStore.MediaColumns.HEIGHT,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.MediaColumns.VOLUME_NAME,
        )
        return appContext.contentResolver.query(
            collection,
            columns,
            "${MediaStore.Images.Media._ID}=?",
            arrayOf(imageId.toString()),
            null,
        )?.use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val idIndex = cursor.getColumnIndex(MediaStore.Images.Media._ID)
            val localId = cursor.longOrNull(idIndex) ?: return@use null
            val local = ImageFingerprint.from(cursor) ?: return@use null
            val volumeIndex = cursor.getColumnIndex(MediaStore.MediaColumns.VOLUME_NAME)
            val volumeName = cursor.stringOrNull(volumeIndex)?.takeIf { it.isNotBlank() }
                ?: return@use null
            if (cursor.moveToNext() || localId != imageId || !source.matches(local)) {
                return@use null
            }
            ContentUris.withAppendedId(
                MediaStore.Images.Media.getContentUri(volumeName), imageId
            ).toString()
        }
    }

    private data class ImageFingerprint(
        val size: Long,
        val mimeType: String,
        val width: Long?,
        val height: Long?,
        val dateTaken: Long?,
    ) {
        fun matches(other: ImageFingerprint): Boolean =
            size == other.size && mimeType.equals(other.mimeType, ignoreCase = true) &&
                (width == null || other.width == null || width == other.width) &&
                (height == null || other.height == null || height == other.height) &&
                (dateTaken == null || other.dateTaken == null || dateTaken == other.dateTaken)

        companion object {
            fun from(cursor: Cursor): ImageFingerprint? {
                val size = cursor.longOrNull(cursor.getColumnIndex(MediaStore.MediaColumns.SIZE))
                    ?.takeIf { it > 0 } ?: return null
                val mime = cursor.stringOrNull(cursor.getColumnIndex(MediaStore.MediaColumns.MIME_TYPE))
                    ?.takeIf { it.startsWith("image/", ignoreCase = true) } ?: return null
                return ImageFingerprint(
                    size = size,
                    mimeType = mime,
                    width = cursor.longOrNull(cursor.getColumnIndex(MediaStore.MediaColumns.WIDTH))
                        ?.takeIf { it > 0 },
                    height = cursor.longOrNull(cursor.getColumnIndex(MediaStore.MediaColumns.HEIGHT))
                        ?.takeIf { it > 0 },
                    dateTaken = cursor.longOrNull(cursor.getColumnIndex(MediaStore.Images.Media.DATE_TAKEN))
                        ?.takeIf { it > 0 },
                )
            }
        }
    }

    private fun queryImages(sorted: Boolean): Cursor {
        val modern = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        val collection = if (modern) {
            MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
        } else {
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        }
        val projection = mutableListOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.BUCKET_ID,
            MediaStore.Images.Media.BUCKET_DISPLAY_NAME,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.DATE_ADDED,
        )
        if (modern) {
            projection += MediaStore.MediaColumns.RELATIVE_PATH
            projection += MediaStore.MediaColumns.VOLUME_NAME
            projection += MediaStore.MediaColumns.OWNER_PACKAGE_NAME
            projection += MediaStore.MediaColumns.IS_PENDING
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                projection += MediaStore.MediaColumns.IS_TRASHED
            }
        } else {
            @Suppress("DEPRECATION")
            projection += MediaStore.MediaColumns.DATA
        }
        // DATE_TAKEN is milliseconds; DATE_ADDED is seconds. Sort before paging so
        // a recently copied old photo keeps its capture-time position.
        val dateOrder = "CASE WHEN ${MediaStore.Images.Media.DATE_TAKEN} > 0 " +
            "THEN ${MediaStore.Images.Media.DATE_TAKEN} " +
            "ELSE ${MediaStore.Images.Media.DATE_ADDED} * 1000 END"
        val sortOrder = if (sorted) {
            "$dateOrder DESC, ${MediaStore.Images.Media._ID} DESC" +
                if (modern) ", ${MediaStore.MediaColumns.VOLUME_NAME} ASC" else ""
        } else null
        try {
            return appContext.contentResolver.query(
                collection, projection.toTypedArray(), null, null, sortOrder
            ) ?: throw IOException("기기 사진 목록을 읽을 수 없습니다")
        } catch (cause: SecurityException) {
            throw IOException("기기 사진 접근 권한을 확인해 주세요", cause)
        }
    }

    private inner class ImageColumns(cursor: Cursor) {
        private val id = cursor.getColumnIndex(MediaStore.Images.Media._ID)
        private val name = cursor.getColumnIndex(MediaStore.Images.Media.DISPLAY_NAME)
        private val bucketId = cursor.getColumnIndex(MediaStore.Images.Media.BUCKET_ID)
        private val bucketName = cursor.getColumnIndex(MediaStore.Images.Media.BUCKET_DISPLAY_NAME)
        private val dateTaken = cursor.getColumnIndex(MediaStore.Images.Media.DATE_TAKEN)
        private val dateAdded = cursor.getColumnIndex(MediaStore.Images.Media.DATE_ADDED)
        private val path = cursor.getColumnIndex(
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                MediaStore.MediaColumns.RELATIVE_PATH
            } else {
                @Suppress("DEPRECATION")
                MediaStore.MediaColumns.DATA
            }
        )
        private val volume = cursor.getColumnIndex(MediaStore.MediaColumns.VOLUME_NAME)
        private val owner = cursor.getColumnIndex(MediaStore.MediaColumns.OWNER_PACKAGE_NAME)
        private val pending = cursor.getColumnIndex(MediaStore.MediaColumns.IS_PENDING)
        private val trashed = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            cursor.getColumnIndex(MediaStore.MediaColumns.IS_TRASHED)
        } else -1

        fun read(cursor: Cursor): ImageRow? {
            val imageId = cursor.longOrNull(id) ?: return null
            if (cursor.longOrNull(pending) == 1L || cursor.longOrNull(trashed) == 1L) {
                return null
            }
            val modern = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
            val volumeName = if (modern) {
                cursor.stringOrNull(volume)?.takeIf { it.isNotBlank() }
                    ?: MediaStore.VOLUME_EXTERNAL
            } else {
                LEGACY_PRIMARY_VOLUME
            }
            val rawPath = cursor.stringOrNull(path)
            val folderPath = if (modern) {
                rawPath?.trimEnd('/')
            } else {
                rawPath?.let { File(it).parent }
            }
            val bucket = cursor.stringOrNull(bucketId).orEmpty()
            // A volume and full folder path distinguish albums with the same name.
            // BUCKET_ID remains a fallback for providers with no path metadata.
            val location = folderPath?.takeIf { it.isNotBlank() } ?: bucket.ifBlank { "unknown" }
            val albumKey = UUID.nameUUIDFromBytes(
                "$volumeName\u0000$location".toByteArray(StandardCharsets.UTF_8)
            ).toString()
            val albumName = cursor.stringOrNull(bucketName)?.trim().orEmpty().ifBlank {
                folderPath?.substringAfterLast('/')?.takeIf { it.isNotBlank() }
                    ?: "이름 없는 앨범"
            }
            val itemCollection = if (modern && volumeName != MediaStore.VOLUME_EXTERNAL) {
                MediaStore.Images.Media.getContentUri(volumeName)
            } else {
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI
            }
            val itemUri = ContentUris.withAppendedId(itemCollection, imageId).toString()
            val displayName = cursor.stringOrNull(name)?.takeIf { it.isNotBlank() }
                ?: "사진 $imageId"
            val taken = cursor.longOrNull(dateTaken)?.takeIf { it > 0 }
            val added = cursor.longOrNull(dateAdded)?.takeIf { it > 0 }
            val sortDate = taken ?: (added ?: 0L) * 1_000L
            val ownerPackage = cursor.stringOrNull(owner)
            return ImageRow(
                id = imageId,
                uri = itemUri,
                displayName = displayName,
                albumKey = albumKey,
                albumName = albumName,
                sortDate = sortDate,
                ownedByApp = ownerPackage == appContext.packageName,
            )
        }
    }

    private data class ImageRow(
        val id: Long,
        val uri: String,
        val displayName: String,
        val albumKey: String,
        val albumName: String,
        val sortDate: Long,
        val ownedByApp: Boolean,
    ) {
        fun isProcessed(hiddenUris: Set<String>): Boolean =
            ownedByApp || uri in hiddenUris || legacyUri() in hiddenUris

        // On Android 10+, the same primary-volume item may have been saved using
        // the older aggregate external URI. Match that alias without guessing IDs
        // for other storage volumes.
        private fun legacyUri(): String {
            val parsed = Uri.parse(uri)
            return if (parsed.pathSegments.firstOrNull() == MediaStore.VOLUME_EXTERNAL_PRIMARY) {
                ContentUris.withAppendedId(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id
                ).toString()
            } else uri
        }
    }

    private data class AlbumCount(
        val key: String,
        val displayName: String,
        var count: Int,
        var coverUri: String,
        var coverDate: Long,
        var coverId: Long,
    )

    companion object {
        /** Pass this key to listPhotos to display images from every album. */
        const val ALL_ALBUM_KEY = ""
        private const val ANDROID_UIDS_PER_USER = 100_000
    }
}

// This format is specific to Android's local Photo Picker provider. A cloud
// provider may also use content://media/picker/..., but has a different embedded
// authority. Never interpret its media ID as a local MediaStore image ID.
private val LOCAL_PICKER_IMAGE_URI = Regex(
    "^content://media/(?:picker|picker_get_content)/([0-9]+)/" +
        "com\\.android\\.providers\\.media\\.photopicker/media/([0-9]+)$"
)

internal fun localPickerImageId(rawUri: String, currentUser: Int): Long? {
    val match = LOCAL_PICKER_IMAGE_URI.matchEntire(rawUri) ?: return null
    val pickerUser = match.groupValues[1].toIntOrNull() ?: return null
    if (pickerUser != currentUser) return null
    return match.groupValues[2].toLongOrNull()?.takeIf { it > 0 }
}

private fun Cursor.longOrNull(index: Int): Long? =
    if (index >= 0 && !isNull(index)) getLong(index) else null

private fun Cursor.stringOrNull(index: Int): String? =
    if (index >= 0 && !isNull(index)) getString(index) else null
