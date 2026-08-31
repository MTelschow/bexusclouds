/* Minimal Unity-compatible test shim - lets test_core run with plain cc
 * when PlatformIO (which bundles real Unity) is not installed.
 * Implements exactly the macros the CLOUDS tests use. */
#ifndef UNITY_MIN_H
#define UNITY_MIN_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

extern int unity_min_failures;
extern int unity_min_tests;
extern const char *unity_min_current;

void setUp(void);
void tearDown(void);

#define UNITY_BEGIN() \
    do { \
        unity_min_failures = 0; \
        unity_min_tests = 0; \
    } while (0)
#define UNITY_END() \
    (printf("%d tests, %d failures\n", unity_min_tests, \
            unity_min_failures), \
     unity_min_failures)

/* An assertion failure returns from fn(), so PASS is printed only if the
 * failure count did not move - otherwise a failing test printed both. */
#define RUN_TEST(fn) \
    do { \
        int failures_before_ = unity_min_failures; \
        unity_min_current = #fn; \
        unity_min_tests++; \
        setUp(); \
        fn(); \
        tearDown(); \
        if (unity_min_failures == failures_before_) \
            printf("PASS %s\n", #fn); \
    } while (0)

#define UNITY_MIN_FAIL(msg) \
    do { \
        printf("FAIL %s (%s:%d): %s\n", unity_min_current, __FILE__, \
               __LINE__, msg); \
        unity_min_failures++; \
        return; \
    } while (0)

#define TEST_ASSERT_TRUE(x) \
    do { if (!(x)) UNITY_MIN_FAIL("expected true: " #x); } while (0)
#define TEST_ASSERT_FALSE(x) \
    do { if (x) UNITY_MIN_FAIL("expected false: " #x); } while (0)
#define TEST_ASSERT_NOT_EQUAL(a, b) \
    do { if ((a) == (b)) UNITY_MIN_FAIL("expected != : " #a " vs " #b); } \
    while (0)

#define UNITY_MIN_EQ(a, b, fmt) \
    do { \
        long long va_ = (long long)(a), vb_ = (long long)(b); \
        if (va_ != vb_) { \
            printf("FAIL %s (%s:%d): expected " fmt " got " fmt \
                   "  [" #a " vs " #b "]\n", \
                   unity_min_current, __FILE__, __LINE__, va_, vb_); \
            unity_min_failures++; \
            return; \
        } \
    } while (0)

#define TEST_ASSERT_EQUAL_INT(a, b) UNITY_MIN_EQ(a, b, "%lld")
#define TEST_ASSERT_EQUAL_INT32(a, b) UNITY_MIN_EQ(a, b, "%lld")
#define TEST_ASSERT_EQUAL_UINT8(a, b) UNITY_MIN_EQ(a, b, "%lld")
#define TEST_ASSERT_EQUAL_UINT16(a, b) UNITY_MIN_EQ(a, b, "%lld")
#define TEST_ASSERT_EQUAL_UINT32(a, b) UNITY_MIN_EQ(a, b, "%lld")
#define TEST_ASSERT_EQUAL_HEX8(a, b) UNITY_MIN_EQ(a, b, "%llx")
#define TEST_ASSERT_EQUAL_HEX16(a, b) UNITY_MIN_EQ(a, b, "%llx")
#define TEST_ASSERT_EQUAL_size_t(a, b) UNITY_MIN_EQ(a, b, "%lld")

/* Same argument order and semantics as real Unity, so `pio test -e native`
 * and this shim agree. */
#define TEST_ASSERT_UINT32_WITHIN(delta, expected, actual) \
    do { \
        unsigned long long e_ = (unsigned long long)(expected); \
        unsigned long long a_ = (unsigned long long)(actual); \
        unsigned long long d_ = (unsigned long long)(delta); \
        unsigned long long diff_ = e_ > a_ ? e_ - a_ : a_ - e_; \
        if (diff_ > d_) { \
            printf("FAIL %s (%s:%d): expected %llu +/- %llu, got %llu" \
                   "  [" #actual "]\n", \
                   unity_min_current, __FILE__, __LINE__, e_, d_, a_); \
            unity_min_failures++; \
            return; \
        } \
    } while (0)

#define TEST_ASSERT_EQUAL_MEMORY(a, b, n) \
    do { \
        if (memcmp((a), (b), (n)) != 0) \
            UNITY_MIN_FAIL("memory differs: " #a " vs " #b); \
    } while (0)

#endif
