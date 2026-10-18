package com.example.photosorter.ui

import android.net.Uri
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.example.photosorter.model.AlbumMapping
import com.example.photosorter.model.DeviceAlbum
import com.example.photosorter.model.PhotoItem
import com.example.photosorter.model.PhotoStatus
import com.example.photosorter.viewmodel.SorterUiState

enum class PhotoAccess { FULL, PARTIAL, DENIED }
enum class AppScreen { HOME, ALBUMS, CLASSIFY }

@Composable
fun PhotoSorterApp(
    state: SorterUiState,
    access: PhotoAccess,
    screen: AppScreen,
    showPermissionGate: Boolean,
    permissionWasRequested: Boolean,
    onConfirmPermission: () -> Unit,
    onReviewPermission: () -> Unit,
    onPermissionLater: () -> Unit,
    onOpenSettings: () -> Unit,
    onNavigateHome: () -> Unit,
    onOpenAlbums: () -> Unit,
    onChoosePhotos: () -> Unit,
    onContinue: () -> Unit,
    onRegisterAlbum: (DeviceAlbum) -> Unit,
    onCreateAlbum: (String) -> Unit,
    onUpdateAlias: (String, String) -> Unit,
    onRemoveAlbum: (String) -> Unit,
    onSubmit: (String) -> Unit,
    onPrevious: () -> Unit,
    onResetSession: () -> Unit,
    onClearError: () -> Unit,
) {
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            if (showPermissionGate) {
                PermissionGate(
                    previouslyRequested = permissionWasRequested,
                    onConfirm = onConfirmPermission,
                    onLater = onPermissionLater,
                    onSettings = onOpenSettings,
                )
            } else {
                BackHandler(enabled = screen != AppScreen.HOME) { onNavigateHome() }
                Scaffold(
                    topBar = {
                        Header(
                            title = when (screen) {
                                AppScreen.HOME -> "등록된 앨범"
                                AppScreen.ALBUMS -> "앨범 선택"
                                AppScreen.CLASSIFY -> if (state.items.isNotEmpty())
                                    "${(state.currentIndex + 1).coerceAtMost(state.items.size)} / ${state.items.size}"
                                else "사진 분류"
                            },
                            onBack = if (screen == AppScreen.HOME) null else onNavigateHome,
                        )
                    }
                ) { innerPadding ->
                    Column(Modifier.fillMaxSize().padding(innerPadding)) {
                        if (state.error != null) {
                            Text(
                                text = state.error,
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                            )
                        }
                        when (screen) {
                            AppScreen.HOME -> HomeScreen(
                                state = state,
                                access = access,
                                onOpenAlbums = onOpenAlbums,
                                onReviewPermission = onReviewPermission,
                                onOpenSettings = onOpenSettings,
                                onChoosePhotos = onChoosePhotos,
                                onContinue = onContinue,
                                onCreateAlbum = onCreateAlbum,
                                onUpdateAlias = onUpdateAlias,
                                onRemoveAlbum = onRemoveAlbum,
                                onClearError = onClearError,
                            )
                            AppScreen.ALBUMS -> AlbumScreen(
                                state = state,
                                access = access,
                                onReviewPermission = onReviewPermission,
                                onOpenSettings = onOpenSettings,
                                onRegister = {
                                    onRegisterAlbum(it)
                                    onNavigateHome()
                                },
                                onCreateAlbum = {
                                    onCreateAlbum(it)
                                    onNavigateHome()
                                },
                            )
                            AppScreen.CLASSIFY -> when {
                                state.items.isEmpty() -> LoadingSelection(state.busy)
                                state.currentIndex >= state.items.size -> CompletionScreen(
                                    state = state,
                                    onChoosePhotos = onChoosePhotos,
                                    onPrevious = onPrevious,
                                    onResetSession = onResetSession,
                                )
                                else -> ClassificationScreen(
                                    state = state,
                                    onSubmit = onSubmit,
                                    onPrevious = onPrevious,
                                    onClearError = onClearError,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Header(title: String, onBack: (() -> Unit)?) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth().statusBarsPadding().height(56.dp)
                .padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (onBack != null) {
                TextButton(onClick = onBack) { Text("뒤로") }
            }
            Text(
                title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = if (onBack == null) 8.dp else 4.dp),
            )
        }
        HorizontalDivider()
    }
}

@Composable
private fun PermissionGate(
    previouslyRequested: Boolean,
    onConfirm: () -> Unit,
    onLater: () -> Unit,
    onSettings: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().systemBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("사진 접근 권한", style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(16.dp))
        Text(
            "휴대폰에 저장된 앨범을 앱 안에서 보여주고, 분류한 사진을 해당 앨범에 복사하려면 사진 접근 권한이 필요합니다. 원본 사진은 수정하거나 삭제하지 않습니다.",
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(12.dp))
        Text(
            "확인을 누르면 Android 권한 선택창이 열립니다. 사진을 일부만 허용하면 앨범 목록도 제한될 수 있습니다.",
            style = MaterialTheme.typography.bodyMedium,
        )
        if (previouslyRequested) {
            Spacer(Modifier.height(12.dp))
            Text("권한을 허용하지 않았다면 다시 요청하거나 설정에서 변경할 수 있습니다.",
                color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.height(28.dp))
        Button(onClick = onConfirm, modifier = Modifier.fillMaxWidth()) {
            Text("확인하고 권한 요청")
        }
        OutlinedButton(onClick = onLater, modifier = Modifier.fillMaxWidth()) {
            Text("나중에")
        }
        TextButton(onClick = onSettings, modifier = Modifier.fillMaxWidth()) {
            Text("앱 설정에서 권한 변경")
        }
    }
}

@Composable
private fun HomeScreen(
    state: SorterUiState,
    access: PhotoAccess,
    onOpenAlbums: () -> Unit,
    onReviewPermission: () -> Unit,
    onOpenSettings: () -> Unit,
    onChoosePhotos: () -> Unit,
    onContinue: () -> Unit,
    onCreateAlbum: (String) -> Unit,
    onUpdateAlias: (String, String) -> Unit,
    onRemoveAlbum: (String) -> Unit,
    onClearError: () -> Unit,
) {
    var editing by remember { mutableStateOf<AlbumMapping?>(null) }
    var showCreate by remember { mutableStateOf(false) }
    var confirmReplace by remember { mutableStateOf(false) }
    val hasUnfinishedSession = state.items.isNotEmpty() && state.currentIndex < state.items.size

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        when (access) {
            PhotoAccess.DENIED -> InfoCard(
                "앨범을 보려면 사진 접근 권한이 필요합니다. 사진 선택기는 지금도 사용할 수 있습니다."
            )
            PhotoAccess.PARTIAL -> {
                InfoCard("선택한 사진에 해당하는 앨범만 보일 수 있습니다.")
                Row {
                    TextButton(onClick = onReviewPermission) { Text("사진 접근 범위 변경") }
                    TextButton(onClick = onOpenSettings) { Text("앱 설정") }
                }
            }
            PhotoAccess.FULL -> Unit
        }

        if (state.mappings.isEmpty()) {
            InfoCard("앨범을 추가하고 사진에 사용할 입력 이름을 확인해 주세요.")
        } else {
            state.mappings.forEach { mapping ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("${mapping.inputName} → ${mapping.albumDisplayName}",
                            style = MaterialTheme.typography.titleMedium)
                        Row {
                            TextButton(onClick = { editing = mapping }) { Text("입력 이름 수정") }
                            TextButton(onClick = { onRemoveAlbum(mapping.id) }) { Text("등록 제거") }
                        }
                    }
                }
            }
        }
        Button(onClick = onOpenAlbums, modifier = Modifier.fillMaxWidth()) { Text("+ 앨범 추가") }
        if (access == PhotoAccess.DENIED && Build.VERSION.SDK_INT >= 29) {
            OutlinedButton(onClick = { showCreate = true }, modifier = Modifier.fillMaxWidth()) {
                Text("+ 새 앨범 만들기")
            }
        }
        if (hasUnfinishedSession) {
            OutlinedButton(onClick = onContinue, modifier = Modifier.fillMaxWidth()) {
                Text("이전 분류 이어서 (${state.currentIndex + 1} / ${state.items.size})")
            }
        }
        Button(
            onClick = {
                if (hasUnfinishedSession) confirmReplace = true else onChoosePhotos()
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("사진 선택하기") }
        Text("사진 선택에는 전체 갤러리 접근 권한이 필요하지 않습니다.",
            style = MaterialTheme.typography.bodySmall)
    }

    if (editing != null) {
        val mapping = editing!!
        var alias by remember(mapping.id) { mutableStateOf(mapping.inputName) }
        AlertDialog(
            onDismissRequest = { editing = null },
            title = { Text("입력 이름 수정") },
            text = {
                OutlinedTextField(
                    value = alias,
                    onValueChange = { alias = it },
                    label = { Text("입력 이름") },
                    singleLine = true,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    onClearError()
                    onUpdateAlias(mapping.id, alias)
                    editing = null
                }) { Text("저장") }
            },
            dismissButton = { TextButton(onClick = { editing = null }) { Text("취소") } },
        )
    }
    if (confirmReplace) {
        AlertDialog(
            onDismissRequest = { confirmReplace = false },
            title = { Text("새 사진을 선택할까요?") },
            text = { Text("현재 분류 진행 상태가 새 사진 목록으로 바뀝니다.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmReplace = false
                    onChoosePhotos()
                }) { Text("새 사진 선택") }
            },
            dismissButton = {
                TextButton(onClick = { confirmReplace = false }) { Text("취소") }
            },
        )
    }
    if (showCreate) {
        AlbumNameDialog(
            onDismiss = { showCreate = false },
            onCreate = { name ->
                showCreate = false
                onCreateAlbum(name)
            },
        )
    }
}

@Composable
private fun AlbumScreen(
    state: SorterUiState,
    access: PhotoAccess,
    onReviewPermission: () -> Unit,
    onOpenSettings: () -> Unit,
    onRegister: (DeviceAlbum) -> Unit,
    onCreateAlbum: (String) -> Unit,
) {
    var showCreate by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize()) {
        if (access == PhotoAccess.PARTIAL) {
            InfoCard("사진 일부만 허용되어 앨범 목록이 제한됩니다.")
            Row(Modifier.padding(horizontal = 12.dp)) {
                TextButton(onClick = onReviewPermission) { Text("사진 접근 범위 변경") }
                TextButton(onClick = onOpenSettings) { Text("앱 설정") }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("기기 앨범", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = { showCreate = true }) { Text("+ 새 앨범") }
        }
        when {
            state.loadingAlbums -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.albums.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("표시할 로컬 앨범이 없습니다. 새 앨범을 만들 수 있습니다.",
                    modifier = Modifier.padding(24.dp), textAlign = TextAlign.Center)
            }
            else -> LazyVerticalGrid(
                columns = GridCells.Adaptive(minSize = 140.dp),
                modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(state.albums, key = { it.id }) { album ->
                    val registered = state.mappings.any { it.id == album.id }
                    Card(
                        modifier = Modifier.fillMaxWidth().clickable(
                            enabled = album.writable && !registered,
                            onClick = { onRegister(album) }
                        ),
                    ) {
                        Column {
                            AsyncImage(
                                model = album.coverUri.takeIf(String::isNotBlank)?.let(Uri::parse),
                                contentDescription = "${album.displayName} 앨범 대표 사진",
                                modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                                contentScale = ContentScale.Crop,
                            )
                            Column(Modifier.padding(10.dp)) {
                                Text(album.displayName, style = MaterialTheme.typography.titleSmall,
                                    maxLines = 2)
                                Text("${album.count}장", style = MaterialTheme.typography.bodySmall)
                                if (registered) Text("등록됨", style = MaterialTheme.typography.labelSmall)
                                else if (!album.writable) Text("저장할 수 없음",
                                    color = MaterialTheme.colorScheme.error,
                                    style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
    }
    if (showCreate) {
        AlbumNameDialog(
            onDismiss = { showCreate = false },
            onCreate = { name ->
                showCreate = false
                onCreateAlbum(name)
            },
        )
    }
}

@Composable
private fun AlbumNameDialog(onDismiss: () -> Unit, onCreate: (String) -> Unit) {
    var albumName by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("새 앨범") },
        text = {
            Column {
                Text("첫 사진을 복사하면 일반 갤러리에도 앨범이 나타납니다.")
                OutlinedTextField(
                    value = albumName,
                    onValueChange = { albumName = it },
                    label = { Text("앨범 이름") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onCreate(albumName) }) { Text("등록") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("취소") } },
    )
}

@Composable
private fun ClassificationScreen(
    state: SorterUiState,
    onSubmit: (String) -> Unit,
    onPrevious: () -> Unit,
    onClearError: () -> Unit,
) {
    val item = state.items[state.currentIndex]
    val focusRequester = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    var input by remember { mutableStateOf("") }
    var imageFailed by remember(item.sourceUri) { mutableStateOf(false) }
    LaunchedEffect(state.currentIndex, item.sourceUri) {
        input = item.inputNames.joinToString(" ")
        focusRequester.requestFocus()
        keyboard?.show()
    }
    Column(Modifier.fillMaxSize().imePadding().padding(horizontal = 12.dp)) {
        Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
            AsyncImage(
                model = Uri.parse(item.sourceUri),
                contentDescription = "분류할 사진 ${state.currentIndex + 1}",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Fit,
                onError = { imageFailed = true },
                onSuccess = { imageFailed = false },
            )
        }
        if (imageFailed) {
            Text("원본 사진을 표시할 수 없습니다. 뒤로 가서 사진을 다시 선택해 주세요.",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium)
        }
        if (item.errorMessage != null) {
            Text(item.errorMessage,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(vertical = 4.dp))
        }
        if (state.busy) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                Text("처리하는 중…")
            }
        }
        OutlinedTextField(
            value = input,
            onValueChange = {
                input = it
                onClearError()
            },
            modifier = Modifier.fillMaxWidth().focusRequester(focusRequester),
            enabled = !imageFailed,
            label = { Text("사람 이름") },
            placeholder = { Text("이름을 공백 또는 쉼표로 구분") },
            supportingText = { Text("빈 채로 완료를 누르면 건너뜁니다.") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = {
                if (!state.busy && !imageFailed) onSubmit(input)
            }),
        )
        if (state.currentIndex > 0) {
            TextButton(onClick = onPrevious, enabled = !state.busy) { Text("이전 사진") }
        }
    }
}

@Composable
private fun CompletionScreen(
    state: SorterUiState,
    onChoosePhotos: () -> Unit,
    onPrevious: () -> Unit,
    onResetSession: () -> Unit,
) {
    val copied = state.items.count { it.status == PhotoStatus.COMPLETED }
    val copiedFiles = state.items.sumOf { it.newCopies.size }
    val skipped = state.items.count { it.status == PhotoStatus.SKIPPED }
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("분류 완료", style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(16.dp))
        Text("전체 ${state.items.size}장 · 분류 ${copied}장 · 복사된 파일 ${copiedFiles}개 · 건너뜀 ${skipped}장")
        Spacer(Modifier.height(24.dp))
        Button(onClick = onChoosePhotos, modifier = Modifier.fillMaxWidth()) {
            Text("새 사진 선택")
        }
        OutlinedButton(onClick = onPrevious, modifier = Modifier.fillMaxWidth()) {
            Text("이전 사진")
        }
        OutlinedButton(onClick = onResetSession, modifier = Modifier.fillMaxWidth()) {
            Text("앨범 화면으로")
        }
    }
}

@Composable
private fun LoadingSelection(busy: Boolean) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (busy) CircularProgressIndicator()
        else Text("사진을 선택하면 분류를 시작합니다.")
    }
}

@Composable
private fun InfoCard(message: String) {
    Card(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
        shape = RoundedCornerShape(12.dp)) {
        Text(message, modifier = Modifier.padding(16.dp),
            style = MaterialTheme.typography.bodyMedium)
    }
}
