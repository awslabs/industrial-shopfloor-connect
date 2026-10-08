## TransformationOperator

[SFC Configuration](./sfc-configuration.md) > [Transformations](./sfc-configuration.md#transformations) 

A transformation, defined in the Transformations section of the top-level SFC configuration, consists of one or more TransformationOperators. Each Transformation operator has a property named "Operator". Depending on the operator type, a Transformation can have no operand, or an operand of which the type depends on that operator.

- [How a transformation is applied](#how-a-transformation-is-applied)
- [Numeric operands](#numeric-operands)
- [Schema](#schema)
- [Examples](#examples)
- [Operators](#operators)

### How a transformation is applied

A transformation is a named list of operators in the [Transformations](./sfc-configuration.md#transformations) section. It is referenced by name from a [channel](./channel-configuration.md#transformation) Transformation, an aggregation output ([Transformations](./aggregation-configuration.md#transformations)), an OPC UA [target](../targets/opcua.md#transformation) or [writer](../targets/opcua-writer.md#transformation) node Transformation, or an [S3 Tables column](../targets/aws-s3-tables.md#transformation) Transformation.

- The operators run in order; each operator receives the result of the previous one.
- If the value is a list and the first operator does not take a list, the chain runs on each element.
- If an operator returns null (Sqrt of a negative number, Divide by 0, AtIndex or MapRange out of range, invalid ParseInt input), the rest of the chain is skipped and the result is null. A schedule without aggregation does not send a channel whose value is null.
- Values are not widened to the input type listed under **Type**, so a Short is not accepted where Int is listed. Convert first with ToInt, ToLong or ToDouble.

### Numeric operands

Numeric operands can be JSON numbers or strings. A value that contains "." is read as a 32-bit float; any other value is read as a 32-bit integer with Integer.decode, so "0xFF" and "#FF" are hexadecimal and a leading 0 means octal ("010" is 8). Write hexadecimal values as strings: a bare 0xFF is not valid JSON.

Plus, Minus, Multiply, Mod, Max, Min and Equals convert the operand to the type of the input value. For Int, Short, Byte or Long input a fractional operand is truncated (Multiply 0.1 on an Int gives 0). Decimal operands are 32-bit floats, so Multiply 0.1 on the Double 25.0 gives 2.500000037252903, and Equals 0.1 never matches a Double 0.1. To scale by a decimal factor use [Divide](#divide) with a whole number: Divide 10 returns a Double for any input except Float.

### Operators

- [Abs](#abs)
- [Acos](#acos)
- [And](#and)
- [Asin](#asin)
- [AtIndex](#atindex)
- [Atan](#atan)
- [BoolToNumber](#booltonumber)
- [BytesToDoubleBE](#bytestodoublebe)
- [BytesToDoubleLE](#bytestodoublele)
- [BytesToFloatBE](#bytestofloatbe)
- [BytesToFloatLE](#bytestofloatle)
- [BytesToInt16](#bytestoint16)
- [Ceil](#ceil)
- [Celsius](#celsius)
- [Chunked](#chunked)
- [Cos](#cos)
- [Cosh](#cosh)
- [DecodeToString](#decodetostring)
- [Divide](#divide)
- [EpocMilliSecondsToTimestamp](#epocmillisecondstotimestamp)
- [EpocSecondsToTimestamp](#epocsecondstotimestamp)
- [Equals](#equals)
- [Exp](#exp)
- [Fahrenheit](#fahrenheit)
- [Flatten](#flatten)
- [Floor](#floor)
- [Int16ToBytes](#int16tobytes)
- [Int16sToInt32](#int16stoint32)
- [Int32ToInt16s](#int32toint16s)
- [IsoDateTimeStrToEpocMilliSeconds](#isodatetimestrtoepocmilliseconds)
- [IsoDateTimeStrToEpocSeconds](#isodatetimestrtoepocseconds)
- [IsoTimeStrToMilliSeconds](#isotimestrtomilliseconds)
- [IsoTimeStrToNanoSeconds](#isotimestrtonanoseconds)
- [IsoTimeStrToSeconds](#isotimestrtoseconds)
- [Ln](#ln)
- [Log10](#log10)
- [Log2](#log2)
- [LowerCase](#lowercase)
- [MapRange](#maprange)
- [MapStringToNumber](#mapstringtonumber)
- [Max](#max)
- [Min](#min)
- [Minus](#minus)
- [Mod](#mod)
- [Multiply](#multiply)
- [Not](#not)
- [NumbersToFloatBE](#numberstofloatbe)
- [NumbersToFloatLE](#numberstofloatle)
- [Or](#or)
- [OutsideRangeExclusive](#outsiderangeexclusive)
- [OutsideRangeInclusive](#outsiderangeinclusive)
- [ParseInt](#parseint)
- [ParseNumber](#parsenumber)
- [Plus](#plus)
- [Query](#query)
- [ReverseList](#reverselist)
- [Round](#round)
- [Shl](#shl)
- [Shr](#shr)
- [Sign](#sign)
- [Sin](#sin)
- [Sinh](#sinh)
- [Sqrt](#sqrt)
- [Str](#str)
- [StrEquals](#strequals)
- [StrEqualsNoCase](#strequalsnocase)
- [SubString](#substring)
- [Tan](#tan)
- [Tanh](#tanh)
- [TimestampToEpocMilliSeconds](#timestamptoepocmilliseconds)
- [TimestampToEpocSeconds](#timestamptoepocseconds)
- [ToByte](#tobyte)
- [ToDouble](#todouble)
- [ToFloat](#tofloat)
- [ToInt](#toint)
- [ToLong](#tolong)
- [ToShort](#toshort)
- [ToSigned](#tosigned)
- [ToUnsigned](#tounsigned)
- [Trunc](#trunc)
- [TruncAt](#truncat)
- [UpperCase](#uppercase)
- [WithinRangeExclusive](#withinrangeexclusive)
- [WithinRangeInclusive](#withinrangeinclusive)
- [Xor](#xor)

---
### Abs
Calculates the absolute value of a number.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
    "Operator": "Abs"
}
```

---
### Acos
Computes the arc cosine, returning an angle in the range from 0.0 to π radians; returns null for values outside -1..1.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
   "Operator": "Acos"
}
```

---
### And
Alias is "&"
Bitwise and of value and parameter.

**Type**: Datatype: Int, Byte, Short, Long

**Operand**: Mask for AND operation

```json
{
   "Operator": "And",
    "Operand": "0xFF"
}
```

---
### Asin
Computes the arc sine, returning an angle in the range from -π/2 to π/2 radians.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
	"Operator": "Asin"
}
```

---
### AtIndex
Alias is "[]"
Returns item from an array at the specified index.

**Type**: Datatype: Any[]

**Operand:** Index of the item; negative values count from the end (-1 is the last item). An index outside the list returns null.



```json
{
	"Operator": "AtIndex",
    "Operand" : 0
}
```

---
### Atan
Computes the arc tangent; the returned value is an angle in the range from - π/2 to  π/2 radians.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
   "Operator": "Atan"
}
```

---
### BoolToNumber
Converts Boolean value to a number. False value returns 0, True value returns 1

**Type**: Datatype: Boolean

**Operand**: None

```json
{
   "Operator": "BoolToNumber"
}
```

---
### BytesToDoubleBE
Converts array of 8 bytes to a double value (Big-Endian)

**Type**: Datatype: byte[8]

**Operand**: None

```json
{
   "Operator": "BytesToDoubleBE"
}
```

---
### BytesToDoubleLE
Converts array of 8 bytes to a double value (Little-Endian)

**Type**: Datatype: byte[8]

**Operand**: None

```json
{
  "Operator": "BytesToDoubleLE"
}
```

---
### BytesToFloatBE
Converts array of 4 bytes to a float value (Big-Endian)

**Type**: Datatype: byte[4]

**Operand**: None

```json
{
  "Operator": "BytesToFloatBE"
}
```

---
### BytesToFloatLE
Converts an array of four bytes into a float value (Little-Endian format).

**Type**: Datatype: byte[4]

**Operand**: None

```json
{
  "Operator": "BytesToFloatLE"
}
```

---
### BytesToInt16
Converts array of two bytes to a 16-bit integer (Big-Endian)

**Type**: Datatype: byte[2]

**Operand**: None

```json
{
  "Operator": "BytesToInt16"
}
```

---
### Ceil
Rounds the value up to the next highest integer.

**Type**: Datatypes: Numeric

**Operand**: None

```json
{
  "Operator": "Ceil"
}
```

---
### Celsius
Converts Fahrenheit temperature to Celsius.

**Type**: Datatypes: Numeric

**Operand**: None

```json
{
  "Operator": "Celsius"
}
```



---
### Chunked
Splits a value, which contains a list of values, into a lists of smaller lists, containing the specified chunk size. The last list may contain items less than the specified chunk size.

**Type**: Datatypes: Lists

**Operand**: Chunk size

```json
{
  "Operator": "Chunked",
  "Operand" : 16
}
```

---
### Cos
Computes the cosine of the angle given in radians

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Cos"
}
```



---
### Cosh
Computes the hyperbolic cosine

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Cosh"
}
```

---
### DecodeToString
Decodes byte arrays (and ByteStrings) into UTF-8 String

**Type**: Datatype: Byte[]

**Operand**: None

```json
{
  "Operator": "DecodeToString"
}
```

---
### Divide
Alias is "/"
Divides values

**Type**: Datatypes: Numeric

**Operand:** Divider (must not be 0; division by 0 returns null). The result is a Double (Float for Float input), e.g. 5 / 2 = 2.5.

```json
{
  "Operator": "Divide",
  "Operand" : 2
}
```

```json
{ 
  "Operator" : "/",
  "Operand" : 10
}
```



---
### EpocMilliSecondsToTimestamp
Obtains a DateTime using milliseconds from the epoch of 1970-01-01T00:00:00Z.

**Type**: Datatypes: Long (convert Int values with ToLong first)

**Operand**: None

```json
{
  "Operator": "EpocMilliSecondsToTimestamp"
}
```

---
### EpocSecondsToTimestamp
Obtains a DateTime using seconds from the epoch of 1970-01-01T00:00:00Z.

**Type**: Datatypes: Long (convert Int values with ToLong first)

**Operand**: None

```json
{
  "Operator": "EpocSecondsToTimestamp"
}
```

---
### Equals
Alias is "==".
Returns true if the value equals the operand, otherwise false.

**Type**: Datatype: Number

**Operand**:  Number to test for equality

```json
{
  "Operator": "Equals",
  "Operand": 1024
}
```

---
### Exp
Calculates the value of e raised to the power of the input value.

**Type**: Datatypes: Numeric

**Operand**: None

```json
{
  "Operator": "Exp"
}
```

---
### Fahrenheit
Converts Celsius temperature to Fahrenheit.

**Type**: Datatypes: Numeric

**Operand**: None

```json
{
  "Operator": "Fahrenheit"
}
```

---
### Flatten
Flatten multi-dimensional array values into a single-dimensional array value. 

**Type**: Datatypes: Any

**Operand**: None

```json
{
  "Operator": "Flatten"
}
```

---
### Floor
Calculates the largest integer less than or equal to the value.

**Type**: Datatypes: Numeric

**Operand**: None

```json
{
  "Operator": "Floor"
}
```

---
### Int16ToBytes
Converts a 16-bit value in an array of 2 8-bit values.

Known limitation: a list returned by this operator as the final value cannot currently be sent to a target that runs in [IPC mode](../sfc-deployment.md#ipc).

**Type**: Datatype: Int (convert a Short, e.g. from BytesToInt16, with ToInt first)

**Operand**: None

```json
{
  "Operator": "Int16ToBytes"
}
```

---
### Int16sToInt32
Converts an array of two 16-bit values into a single 32-bit value. The first element is the high word; apply ReverseList first for low-word-first devices.

**Type**: Datatypes: int16[2]

**Operand**: None

```json
{
  "Operator": "Int16sToInt32"
}
```

---
### Int32ToInt16s
Converts a 32-bit value in an array of 2 16-bit values.

Known limitation: a list returned by this operator as the final value cannot currently be sent to a target that runs in [IPC mode](../sfc-deployment.md#ipc).

**Type**: Datatype: 32-bit Value

**Operand**: None

```json
{
  "Operator": "Int32ToInt16s"
}
```

---
### IsoDateTimeStrToEpocMilliSeconds
Converts a string in a format such as 2007-12-03T10:15:30.00Z into the number of milliseconds from the epoch of 1970-01-01T00:00:00Z, as a Long.
The string must represent a valid instant in UTC

**Type**: Datatype : String

**Operand**: None

```json
{
  "Operator": "IsoDateTimeStrToEpocMilliSeconds"
}
```

---
### IsoDateTimeStrToEpocSeconds
Converts a string in a format such as 2007-12-03T10:15:30.00Z into the number of seconds from the epoch of 1970-01-01T00:00:00Z, as a Long.
The string must represent a valid instant in UTC

**Type**: Datatype : String

**Operand**: None

```json
{
  "Operator": "IsoDateTimeStrToEpocSeconds"
}
```

---
### IsoTimeStrToMilliSeconds
Converts a string representing a duration in ISO-8601 format into milliseconds.

**Type**: Datatype : String

**Operand**: None

```json
{
  "Operator": "IsoTimeStrToMilliSeconds"
}
```

---
### IsoTimeStrToNanoSeconds
Converts a string representing a duration in ISO-8601 format into nanoseconds.

**Type**: Datatype : String

**Operand**: None

```json
{
  "Operator": "IsoTimeStrToNanoSeconds"
}
```

---
### IsoTimeStrToSeconds
Converts a string in ISO-8601 duration format into seconds

**Type**: Datatype : String

**Operand**: None

```json
{
  "Operator": "IsoTimeStrToSeconds"
}
```

---
### Ln
Calculates the natural logarithm (base E).

**Type**: Datatypes: Numeric

**Operand**: None

```json
{
  "Operator": "Ln"
}
```

---
### Log10
Computes the common logarithm (base 10)

Known limitation: only Float input currently returns the base 10 logarithm; Double and integer inputs return the natural logarithm (as [Ln](#ln)). Put ToFloat first to get base 10.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Log10"
}
```

---
### Log2
Computes the binary logarithm (base 2)

Known limitation: only Float input currently returns the base 2 logarithm; Double and integer inputs return the natural logarithm (as [Ln](#ln)). Put ToFloat first to get base 2.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Log2"
}
```

---
### LowerCase
Converts string to lowercase.

**Type**: Datatype: String

**Operand**: None

```json
{
  "Operator": "LowerCase"
}
```

---
### MapRange
Maps numerical ranges.

**Type**: Datatype: Numeric

**Operand:**  Structure containing both input and output range.

```json
{
   "Operator" : "MapRange",
   "Operand" : {
        "From": {
           "MinValue": 0,
           "MaxValue": 1024
        },
        "To": {
          "MinValue": 0,
          "MaxValue": 100
       }
   }
}
```
Maps range 0-1024 to range 0-100. Values outside the From range return null; Int, Byte and Long inputs return a rounded Long.

---
### MapStringToNumber
Maps a string value to an integer value or default value.

**Type**: Datatype: String



```json
{
   "Operator": "MapStringToNumber",
   "Operand": {
     "Map": {
       "A": 1,
       "B": 2
     },
     "Default": 0
   }
}

```

**Operand**: `Map` - object that maps strings to integers; `Default` - integer returned when a string has no mapping (default 0).

---
### Max
Returns greater of value or parameter value. The operand is converted to the type of the input value, see [Numeric operands](#numeric-operands).

**Type**: Datatype: Numeric

**Operand**: Numeric test value

```json
{
  "Operator": "Max",
  "Operand" : 0
}
```

---
### Min
Return smallest of value or parameter value. The operand is converted to the type of the input value, see [Numeric operands](#numeric-operands).

**Type**: Datatype: Numeric

**Operand**: Numeric test value

```json
{
  "Operator": "Min",
  "Operand" : 0
}
```

---
### Minus
alias is "-"
Subtracts the parameter value from the actual value. The operand is converted to the type of the input value, see [Numeric operands](#numeric-operands).

**Type**: Datatype: Numeric

**Operand**: Numeric value to subtract

```json
{
  "Operator": "Minus",
  "Operand" : 10
}
```

```json
{ 
  "Operator" : "-",
  "Operand" : 10
}
```

---
### Mod
alias is "%"
Calculates the remainder when a value is divided by a parameter value. The operand is converted to the type of the input value, see [Numeric operands](#numeric-operands).

**Type**: Datatype: Numeric

**Operand**:  Divider

```json
{
  "Operator": "Mod",
  "Operand" : 16
}
```

```json
{ 
  "Operator" : "%",
  "Operand" : 10
}
```

---
### Multiply
alias is "*"
Multiplies value by parameter value.

The operand is converted to the type of the input value: Multiply 0.1 on an Int gives 0, and on the Double 25.0 it gives 2.500000037252903. To scale by a decimal factor use [Divide](#divide), for example Divide 10. See [Numeric operands](#numeric-operands).

**Type**: Datatype: Numeric

**Operand**: Parameter: Multiplier

```json
{
  "Operator": "Multiply",
  "Operand" : 2
}
```

```json
{ 
  "Operator" : "*",
  "Operand" : 2
}
```

---
### Not
alias is "!"
Inverts the value of a Boolean variable.

**Type**: Datatype : Boolean

**Operand**: None

```json
{
  "Operator": "Not"
}
```

---
### NumbersToFloatBE
Takes a list of two numbers and converts the individual bytes of these numbers into a float value using Big Endian encoding.

**Type**: Datatype: List of size 2 containing 2 numeric values. These values are first converted into 16-bit words from which the float value is decoded. 

**Operand**: None

```json
{
  "Operator": "NumbersToFloatBE"
}
```

---
### NumbersToFloatLE
Takes a list of two numbers and converts the individual bytes of these numbers into a float value using Little Endian encoding.

**Type**: Datatype : List of size 2 containing 2 numeric values. These values are first converted into 16 bit words from which the float value is decoded. 

**Operand**: None

```json
{
  "Operator": "NumbersToFloatLE"
}
```

---
### Or
Alias = "|"
Bitwise or of value and parameter.

**Type**: Datatype: Int, Byte, Short, Long.

**Operand**:  or mask

```json
{
  "Operator": "Or",
  "Operand" : "0xFF"
}
```

---
### OutsideRangeExclusive
Returns true if the value is < MinValue or > MaxValue (the bounds count as inside).

**Type**: Datatype: Numeric

**Operand**: Range with MinValue and MaxValue

```json
{
   "Operator": "OutsideRangeExclusive",
   	  "Operand": {
        "MinValue": 0,
        "MaxValue": 100
     }
}
```



---
### OutsideRangeInclusive
Returns true if the value is <= MinValue or >= MaxValue (the bounds count as outside).

**Type**: Datatype: Numeric

**Operand**: Range with MinValue and MaxValue

```json
{
   "Operator": "OutsideRangeInclusive",
   "Operand": {
      "MinValue": 0,
      "MaxValue": 100
   }
}
```


---
### ParseInt
Parses a string as a 32-bit integer with Integer.decode: "0x1F" and "#1F" are hex, a leading 0 is octal ("010" is 8); returns null if the string is invalid. Use ParseNumber for decimals.

**Type**: Datatype: String

**Operand**: None

```json
{
  "Operator": "ParseInt"
}
```

---
### ParseNumber
Parses a string value as a double number. The string must be a valid representation of a number.

**Type**: Datatype: String

**Operand**: None

```json
{
  "Operator": "ParseNumber"
}
```

---
### Plus
alias is "+" or "Add"
Adds the value of the parameter to the value. The operand is converted to the type of the input value, see [Numeric operands](#numeric-operands).

**Type**: Datatype: Numeric

**Operand**: Numeric value to add

```json
{
  "Operator": "Plus",
  "Operand" : 10
}
```

```json
{ 
  "Operator" : "+",
  "Operand" : 10
}
```

---
### Query
Evaluate a JMESpath query against structured data type and returns the result, or null if nothing matches.

**Type**: Datatype: Any (structure, map or list)

**Operand**: JMESPath expression, see https://jmespath.org/

```json
{
  "Operator": "Query",
  "Operand" : "@.PUMP.values.PRESSURE.value"
}
```

---
### ReverseList
Reverses the order of elements in a list.

**Type**: Datatype: Lists

**Operand**: None

```json
{
  "Operator": "ReverseList"
}
```

---
### Round
Rounds the given value towards the closest integer. Ties go to the even neighbour (2.5 becomes 2.0, 3.5 becomes 4.0); integer inputs are returned unchanged.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Round"
}
```

---
### Shl
Alias is "<<"
Shifts this value left by a bit-count number of bits.

**Type**: Datatype: Int, Byte, Short, Long

**Operand**: bit-count

```json
{
  "Operator": "Shl",
  "Operand" : 2
}
```

---
### Shr
Alias is ">>"
Shifts this value right by a bit-count number of bits (arithmetic shift, keeps the sign).

**Type**: Datatype: Int, Byte, Short, Long

**Operand**: bit-count



```json
{
  "Operator": "Shr",
  "Operand" : 2
}
```



---
### Sign
Returns the sign of the value.

- -1.0 if the value is negative
- zero if the value is zero
- 1.0 if the value is positive

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Sign"
}
```

---
### Sin
Computes the sine of the angle given in radians

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Sin"
}
```

---
### Sinh
Computes the hyperbolic sine of the value

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Sinh"
}
```

---
### Sqrt
Calculates the positive square root of a number.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Sqrt"
}
```

---
### Str
String representation of a value.

**Type**: Datatype: Any

**Operand**: None

```json
{
  "Operator": "Str"
}
```

---
### StrEquals
Compares string value with a string parameter.

**Type**: Datatype: String

**Operand**: Parameter: String to test for equality

```json
{
  "Operator": "StrEquals",
  "Operand" : "OK"
}
```

---
### StrEqualsNoCase
Compares string value with a string parameter, ignoring case. Returns true if they are equal, otherwise false.

**Type**: Datatype: String

**Operand**: Parameter: String to test for equality

```json
{
  "Operator": "StrEqualsNoCase",
  "Operand" : "ok"
}
```

---
### SubString
Returns the substring of string value starting at the start and ending right before the end.
Start and End are zero-based indexes when positive and automatically limited to the max length of the input string.

When using negative values, it is the offset from the end of the input string (-1 is the last character).

If Start is omitted, its default value is 0, for the beginning of the string.

If End is omitted, the substring runs to the end of the input string.

**Type**: Datatype: String

**Operand:** Start and end position

```json

{
   "Operator": "SubString",
   "Operand": {
       "Start": 2,
       "End": 4
   }
}
```

---
### Tan
Computes the tangent of the angle given in radians

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Tan"
}
```

---
### Tanh
Calculates the hyperbolic tangent of the input value.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Tanh"
}
```

---
### TimestampToEpocMilliSeconds
Converts a datetime value  to the number of milliseconds from the epoch of 1970-01-01T00:00:00Z.

**Type**: Datatype: DateTime/Timestamp

**Operand**: None

```json
{
  "Operator": "TimestampToEpocMilliSeconds"
}
```

---
### TimestampToEpocSeconds
Converts a datetime value into the number of seconds since the epoch of January 1, 1970, at 00:00:00 UTC.

**Type**: Datatype: DateTime/Timestamp

**Operand**: None

```json
{
  "Operator": "TimestampToEpocSeconds"
}
```



---
### ToByte
Converts a numeric value into a byte value.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToByte"
}
```

---
### ToDouble
Converts numeric value to a double value

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToDouble"
}
```

---
### ToFloat
Converts a numeric value into a floating-point number.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToFloat"
}
```

---
### ToInt
Converts a numeric value into an integer value.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToInt"
}
```

---
### ToLong
Converts a numeric value into a long 64-bit value.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToLong"
}
```

---
### ToShort
Converts a numeric value into a short 16-bit value.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToShort"
}
```

---
### ToSigned
Converts a numeric value into a signed value.

Unsigned values: in the uberjar and in-process [deployment modes](../sfc-deployment.md#choose-a-deployment-mode) unsigned values are converted to signed values of the same width before the first operator (UShort 40000 becomes -25536, so Divide 10 gives -2553.6). With an IPC adapter single values arrive widened (UShort to Int, UInt to Long), so the same transformation gives 4000.0. For 8-bit and 16-bit values, ToInt followed by And "0xFF" or "0xFFFF" gives the unsigned value in every mode.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToSigned"
}
```

---
### ToUnsigned
Converts a numeric value to an unsigned integer.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "ToUnsigned"
}
```

---
### Trunc
Truncates a number to an integer by removing the fractional part of the number.

**Type**: Datatype: Numeric

**Operand**: None

```json
{
  "Operator": "Trunc"
}
```

---
### TruncAt
Truncates (does not round) the value to the given number of decimals: TruncAt 2 turns 2.999 into 2.99. A negative operand truncates integer digits: TruncAt -1 turns 1234 into 1230.

**Type**: Datatype: Numeric

**Operand**: Number of decimals to truncate value at

```json
{
  "Operator": "TruncAt",
  "Operand" : 2
}
```

---
### UpperCase
Converts a string to uppercase.

**Type**: Datatype: String

**Operand**: None

```json
{
  "Operator": "UpperCase"
}
```



---
### WithinRangeExclusive
Tests if values fall within the exclusive range.

**Type**: Datatype : Numeric

**Operand**: Range

```json
{
    "Operator": "WithinRangeExclusive",
    "Operand": {
        "MinValue": 0,
        "MaxValue": 100
    }
}
```



---
### WithinRangeInclusive
Tests if values fall within the inclusive range.

**Type**: Datatype: Numeric



```json
{
"Operator": "WithinRangeInclusive",
  "Operand": {
    "MinValue": 0,
    "MaxValue": 100
	}
}
```

**Operand** : Range

---
### Xor
alias is "^"
Bitwise xor of value and parameter.

**Type**: Datatype: Int, Byte, Short, Long

**Operand** : Parameter: xor mask

```json
{
  "Operator": "Xor",
  "Operand" : "0xFF"
}
```



[^top](#transformationoperator)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "title": "Transformation Operator",
  "description": "Configuration for a transformation operator",
  "properties": {
    "Operator": {
      "type": "string",
      "description": "The transformation operator to apply"
    },
    "Operand": {
     "description": "The operand value for the transformation"
    }
  },
  "required": ["Operator"]
}

```

## Examples

A transformation with two operators that converts a Fahrenheit value to Celsius and truncates the result to one decimal (77.5 becomes 25.2):

```json
{
  "Transformations": {
    "CelsiusOneDecimal": [
      { "Operator": "Celsius" },
      { "Operator": "TruncAt", "Operand": 1 }
    ]
  }
}
```

A channel of a source that references it by name. The channel also needs the properties of its protocol adapter, for example NodeId for OPC UA:

```json
{
  "Channels": {
    "OvenTemperature": {
      "Transformation": "CelsiusOneDecimal"
    }
  }
}
```

See the sections of the operators above for an example of each operator.

**Runnable examples:** [OPC UA to AWS IoT Core using filters](../../examples/opcua-to-iot-using-filters/README.md) ([TruncAt](#truncat) on channels) · [S7 to OPC UA](../../examples/in-process-s7-opcua/README.md) ([Celsius](#celsius) and [ToInt](#toint) on an OPC UA target variable)
