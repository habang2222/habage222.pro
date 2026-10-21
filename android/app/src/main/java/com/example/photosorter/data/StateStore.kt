package com.example.photosorter.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.example.photosorter.model.AlbumMapping
import com.example.photosorter.model.PhotoItem
import com.example.photosorter.model.PhotoStatus
import com.example.photosorter.model.SorterData
import com.example.photosorter.model.targetKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

private val Context.sorterPreferences by preferencesDataStore(name = "photo_sorter")
private val savedStateKey = stringPreferencesKey("sorter_data_v1")

/** Atomically persists the session, including per-album copy successes for safe retries. */
class StateStore(context: Context) {
    private val appContext = context.applicationContext

    suspend fun load(): SorterData = withContext(Dispatchers.IO) {
        val json = appContext.sorterPreferences.data.first()[savedStateKey]
            ?: return@withContext SorterData()
        try {
            decode(json)
        } catch (error: Exception) {
            // Never replace a damaged record with an empty session: that could hide completed copies.
            throw IOException("저장된 사진 분류 기록을 읽을 수 없습니다", error)
        }
    }

    suspend fun save(data: SorterData) {
        val encoded = withContext(Dispatchers.Default) { encode(data) }
        appContext.sorterPreferences.edit { preferences ->
            preferences[savedStateKey] = encoded
        }
    }

    private fun encode(data: SorterData): String = JSONObject().apply {
        put("version", 5)
        put("currentIndex", data.currentIndex)
        put("copyLedger", JSONObject().apply {
            data.copyLedger.forEach { (sourceUri, targetIds) ->
                put(sourceUri, JSONArray(targetIds.toList()))
            }
        })
        put("createdCopyUris", JSONArray(data.createdCopyUris.toList()))
        put("mappings", JSONArray().apply {
            data.mappings.forEach { mapping ->
                put(JSONObject().apply {
                    put("id", mapping.id)
                    put("inputName", mapping.inputName)
                    put("albumDisplayName", mapping.albumDisplayName)
                    put("bucketId", mapping.bucketId ?: JSONObject.NULL)
                    put("volumeName", mapping.volumeName)
                    put("relativePath", mapping.relativePath)
                    put("isAppCreated", mapping.isAppCreated)
                })
            }
        })
        put("items", JSONArray().apply {
            data.items.forEach { item ->
                put(JSONObject().apply {
                    put("sourceUri", item.sourceUri)
                    put("displayName", item.displayName)
                    put("mimeType", item.mimeType)
                    put("status", item.status.name)
                    put("inputNames", JSONArray(item.inputNames))
                    put("selectedTargets", JSONArray(item.selectedTargets.toList()))
                    put("completedTargets", JSONArray(item.completedTargets.toList()))
                    put("newCopies", JSONArray(item.newCopies.toList()))
                    put("errorMessage", item.errorMessage ?: JSONObject.NULL)
                })
            }
        })
    }.toString()

    private fun decode(json: String): SorterData {
        val root = JSONObject(json)
        val version = root.getInt("version")
        if (version !in 1..5) {
            throw IOException("지원되지 않는 저장 데이터 버전입니다")
        }

        val mappingsArray = root.getJSONArray("mappings")
        val mappings = buildList(mappingsArray.length()) {
            for (index in 0 until mappingsArray.length()) {
                val value = mappingsArray.getJSONObject(index)
                add(AlbumMapping(
                    id = value.getString("id"),
                    inputName = value.getString("inputName"),
                    albumDisplayName = value.getString("albumDisplayName"),
                    bucketId = value.nullableString("bucketId"),
                    volumeName = value.getString("volumeName"),
                    relativePath = value.getString("relativePath"),
                    isAppCreated = value.getBoolean("isAppCreated"),
                ))
            }
        }
        val legacyIds = mappings.associate { it.id to it.targetKey() }
        fun targetKeys(values: List<String>): Set<String> = values.map { legacyIds[it] ?: it }.toSet()
        val targetByAlias = mappings.associate { it.inputName to it.targetKey() }

        val itemsArray = root.getJSONArray("items")
        val items = buildList(itemsArray.length()) {
            for (index in 0 until itemsArray.length()) {
                val value = itemsArray.getJSONObject(index)
                val inputNames = value.getJSONArray("inputNames").strings()
                add(PhotoItem(
                    sourceUri = value.getString("sourceUri"),
                    displayName = value.getString("displayName"),
                    mimeType = value.getString("mimeType"),
                    status = PhotoStatus.valueOf(value.getString("status")),
                    inputNames = inputNames,
                    selectedTargets = if (version >= 4) {
                        targetKeys(value.optJSONArray("selectedTargets")?.strings().orEmpty())
                    } else {
                        inputNames.mapNotNull(targetByAlias::get).toSet()
                    },
                    completedTargets = targetKeys(value.getJSONArray("completedTargets").strings()),
                    newCopies = if (version >= 3) {
                        targetKeys(value.optJSONArray("newCopies")?.strings().orEmpty())
                    } else {
                        targetKeys(value.getJSONArray("completedTargets").strings())
                    },
                    errorMessage = value.nullableString("errorMessage"),
                ))
            }
        }
        val savedLedger = root.optJSONObject("copyLedger")?.let { ledger ->
            buildMap {
                val sourceUris = ledger.keys()
                while (sourceUris.hasNext()) {
                    val sourceUri = sourceUris.next()
                    put(sourceUri, targetKeys(ledger.getJSONArray(sourceUri).strings()))
                }
            }
        } ?: emptyMap()
        // v1 did not have a ledger. Merge item records even for v2 so a copied target
        // remains known if an earlier save was interrupted between item and ledger updates.
        val copyLedger = savedLedger.toMutableMap()
        items.forEach { item ->
            if (item.completedTargets.isNotEmpty()) {
                copyLedger[item.sourceUri] = copyLedger[item.sourceUri].orEmpty() + item.completedTargets
            }
        }
        return SorterData(
            mappings = mappings,
            items = items,
            currentIndex = root.getInt("currentIndex").coerceIn(0, items.size),
            copyLedger = copyLedger,
            createdCopyUris = if (version >= 5) {
                root.optJSONArray("createdCopyUris")?.strings().orEmpty().toSet()
            } else emptySet(),
        )
    }

    private fun JSONObject.nullableString(name: String): String? =
        if (isNull(name)) null else getString(name)

    private fun JSONArray.strings(): List<String> =
        List(length()) { index -> getString(index) }
}
