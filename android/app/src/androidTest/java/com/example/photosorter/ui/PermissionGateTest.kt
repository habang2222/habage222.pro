package com.example.photosorter.ui

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.example.photosorter.viewmodel.SorterUiState
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class PermissionGateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun systemRequestStartsOnlyAfterUserConfirmsExplanation() {
        val confirmed = AtomicBoolean(false)
        compose.setContent {
            PhotoSorterApp(
                state = SorterUiState(),
                access = PhotoAccess.DENIED,
                screen = AppScreen.HOME,
                showPermissionGate = true,
                permissionWasRequested = false,
                onConfirmPermission = { confirmed.set(true) },
                onReviewPermission = {},
                onPermissionLater = {},
                onOpenSettings = {},
                onNavigateHome = {},
                onOpenAlbums = {},
                onChoosePhotos = {},
                onContinue = {},
                onRegisterAlbum = {},
                onCreateAlbum = {},
                onUpdateAlias = { _, _ -> },
                onRemoveAlbum = {},
                onSubmit = {},
                onPrevious = {},
                onResetSession = {},
                onClearError = {},
            )
        }
        compose.onNodeWithText("사진 접근 권한").assertExists()
        assertTrue(!confirmed.get())
        compose.onNodeWithText("확인하고 권한 요청").performClick()
        assertTrue(confirmed.get())
    }
}
