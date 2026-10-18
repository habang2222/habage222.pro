package com.example.photosorter.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

class NameParsingTest {
    @Test
    fun mixedSeparatorsAndRepeatedNamesProduceOneCopyTargetEach() {
        assertEquals(
            listOf("김유찬", "이은채", "정하윤"),
            PhotoSorterViewModel.parseNames("  김유찬,,이은채   김유찬, 정하윤  "),
        )
    }

    @Test
    fun emptyOrSeparatorOnlyInputMeansSkip() {
        assertEquals(emptyList<String>(), PhotoSorterViewModel.parseNames(""))
        assertEquals(emptyList<String>(), PhotoSorterViewModel.parseNames(" ,  ,, \t "))
    }
}
