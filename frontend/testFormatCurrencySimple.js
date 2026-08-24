import { strict as assert } from 'node:assert';

// 复制修复后的 formatCurrency 函数
const formatCurrency = (value) => {
    if (value === null || value === undefined) {
        return "UNAVAILABLE";
    }
    const strValue = String(value).trim();
    const decimalPattern = /^-?\d+(?:\.\d+)?$/;
    if (!decimalPattern.test(strValue)) {
        return "UNAVAILABLE";
    }
    
    const parts = strValue.split('.');
    let integerPart = parts[0];
    const fractionPart = parts[1];
    
    if (!/^-?\d+$/.test(integerPart) || (fractionPart && fractionPart.length > 10)) {
        return "UNAVAILABLE";
    }
    
    // 处理负数符号
    const isNegative = integerPart.startsWith("-");
    if (isNegative) {
        integerPart = integerPart.slice(1);
    }
    
    // 格式化整数部分（每3位添加逗号）
    const formattedInteger = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    
    // 构建格式化后的字符串，保留原始小数精度
    let formattedNumber;
    if (fractionPart !== undefined) {
        formattedNumber = `${formattedInteger}.${fractionPart}`;
    } else {
        // 如果没有小数部分，不添加小数点
        formattedNumber = formattedInteger;
    }
    
    // 添加货币符号和负号
    return `${isNegative ? "-" : ""}$${formattedNumber}`;
};

// 测试用例
console.log('=== formatCurrency 测试 ===');

// 测试正常情况
console.log("\n1. 标准货币格式:");
console.log(`"10000.00" -> "${formatCurrency("10000.00")}"`); // 应返回 "$10,000.00"

console.log("\n2. 单小数点:");
console.log(`"0.10" -> "${formatCurrency("0.10")}"`); // 应返回 "$0.10"

console.log("\n3. 负数:");
console.log(`"-25.50" -> "${formatCurrency("-25.50")}"`); // 应返回 "-$25.50"

console.log("\n4. 非常大的数字:");
console.log(`"9007199254740993.01" -> "${formatCurrency("9007199254740993.01")}"`); // 应返回 "$9,007,199,254,740,993.01"

console.log("\n5. 极长数字:");
console.log(`"123456789012345678901234567890.12" -> "${formatCurrency("123456789012345678901234567890.12")}"`); // 应返回 "$123,456,789,012,345,678,901,234,567,890.12"

console.log("\n6. 非常小的小数:");
console.log(`"0.00000001" -> "${formatCurrency("0.00000001")}"`); // 应返回 "$0.00000001"

console.log("\n7. 尾随零:");
console.log(`"1.2300" -> "${formatCurrency("1.2300")}"`); // 应返回 "$1.2300"

// 测试边界情况
console.log("\n=== 边界情况测试 ===\n");

console.log("8. null:");
console.log(`null -> "${formatCurrency(null)}"`); // 应返回 "UNAVAILABLE"

console.log("\n9. undefined:");
console.log(`undefined -> "${formatCurrency(undefined)}"`); // 应返回 "UNAVAILABLE"

console.log("\n10. 空字符串:");
console.log(`"" -> "${formatCurrency("")}"`); // 应返回 "UNAVAILABLE"

console.log("\n11. 非数字字符串:");
console.log(`"abc" -> "${formatCurrency("abc")}"`); // 应返回 "UNAVAILABLE"

console.log("\n12. NaN:");
console.log(`NaN -> "${formatCurrency(NaN)}"`); // 应返回 "UNAVAILABLE"

console.log("\n13. Infinity:");
console.log(`Infinity -> "${formatCurrency(Infinity)}"`); // 应返回 "UNAVAILABLE"

console.log("\n=== 断言测试 ===\n");
try {
    assert.strictEqual(formatCurrency("10000.00"), "$10,000.00");
    assert.strictEqual(formatCurrency("0.10"), "$0.10");
    assert.strictEqual(formatCurrency("-25.50"), "-$25.50");
    assert.strictEqual(formatCurrency("9007199254740993.01"), "$9,007,199,254,740,993.01");
    assert.strictEqual(formatCurrency("123456789012345678901234567890.12"), "$123,456,789,012,345,678,901,234,567,890.12");
    assert.strictEqual(formatCurrency("0.00000001"), "$0.00000001");
    assert.strictEqual(formatCurrency("1.2300"), "$1.2300");
    assert.strictEqual(formatCurrency(null), "UNAVAILABLE");
    assert.strictEqual(formatCurrency(undefined), "UNAVAILABLE");
    assert.strictEqual(formatCurrency(""), "UNAVAILABLE");
    assert.strictEqual(formatCurrency("abc"), "UNAVAILABLE");
    assert.strictEqual(formatCurrency(NaN), "UNAVAILABLE");
    assert.strictEqual(formatCurrency(Infinity), "UNAVAILABLE");
    
    console.log("✅ 所有测试通过!");
} catch (error) {
    console.log(`❌ 测试失败: ${error.message}`);
    console.log(`实际值: ${error.actual}`);
    console.log(`期望值: ${error.expected}`);
}